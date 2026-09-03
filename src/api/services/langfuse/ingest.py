"""Orchestrate Langfuse trace ingestion into Postgres.

Fetch a closed time window (ascending), parse each trace against the AgentState
contract, idempotently upsert rows, and record a ``langfuse_ingestion_runs`` row
with watermark + drift-observability metrics (fill rates, soft-FK resolve rates,
unrecognized-contract rate).

Token counts and cost come from the window's **generation observations**, fetched
once per window (not once per trace) and grouped by trace id — the message stream
in ``trace.output`` cannot see LLM calls made inside tools. If that fetch fails
the window still ingests, on message-derived usage; ``agent_tokens``'s fill rate
in the run row is the signal that this happened.

Watermark advances only at a fully-completed window/chunk boundary; a chunk that
fails after retries aborts the run (no silent gaps), leaving the watermark on the
last contiguous good chunk so the next run resumes there.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.data_models import LangfuseIngestionRunOrm, LangfuseTraceOrm
from src.api.services.langfuse import parse as P
from src.api.services.langfuse.fetch import LangfuseClient, LangfuseFetchError
from src.shared.langfuse_tracing import AUXILIARY_TAG
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

# Langfuse caps list page size (a 300 request 400s); 50 is proven-safe.
MAX_PAGE_SIZE = 50

# A trace near the end of a window has children that start after the window
# closes, so the observation fetch reaches past ``to_ts`` by this much. Observed
# trace latency is tens of seconds; the pad is deliberately far larger, and
# over-fetching is free because observations for traces outside this window's
# trace set are discarded.
OBSERVATION_WINDOW_PAD = timedelta(minutes=30)

# Real columns whose population we monitor for drift (fill-rate per run).
MONITORED_COLS = (
    "prompt",
    "answer",
    "outcome",
    "aoi_name",
    "aoi_type",
    "primary_dataset_name",
    "insight_id",
    "turn_tokens",
    "has_answer",
    # Null whenever the observation fetch produced nothing, which is how a
    # regression back to message-only usage shows up in the run row.
    "agent_tokens",
    "total_cost",
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(raw: Any) -> Optional[datetime]:
    if not isinstance(raw, str) or not raw.strip():
        return None
    s = raw.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _strip_nul(value: Any) -> Any:
    """Recursively drop NUL (U+0000) from strings. Postgres text and jsonb
    reject 0x00, so an unsanitized trace text would abort the whole batch."""
    if isinstance(value, str):
        return value.replace("\x00", "") if "\x00" in value else value
    if isinstance(value, dict):
        return {_strip_nul(k): _strip_nul(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_strip_nul(v) for v in value]
    return value


# --------------------------------------------------------------------------- #
# Row building
# --------------------------------------------------------------------------- #
def build_row(
    trace: dict[str, Any],
    observations: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Map a trace to a langfuse_traces (derived analytics) row dict. Parse
    failures still yield a row (identity + parse_error) so one bad trace never
    aborts the batch.

    ``observations`` is this trace's generation observations, when they could be
    fetched; see ``parse.parse_trace``."""
    session_id = trace.get("sessionId")
    # Turn position + per-turn diffs are cross-row. Session rows carry None and are
    # filled by the post-upsert recompute; null-session rows are singleton threads
    # (COALESCE(session_id, id)) never renumbered, so they're set directly below.
    is_singleton = session_id is None
    row: dict[str, Any] = {
        "id": trace.get("id"),
        "session_id": session_id,
        "user_id": trace.get("userId"),
        "environment": trace.get("environment"),
        "trace_timestamp": _parse_dt(trace.get("timestamp")),
        "trace_updated_at": _parse_dt(trace.get("updatedAt")),
        "latency_seconds": trace.get("latency"),
        # Overwritten from COLUMN_KEYS below; kept here so a parse failure
        # still records whatever cost the trace itself reported.
        "total_cost": trace.get("totalCost"),
        "turn_index": 1 if is_singleton else None,
        "is_final_turn_in_thread": True if is_singleton else None,
        "insight_created_this_turn": None,
        "datasets_analysed_this_turn": None,
        "parsed_at": _utcnow(),
        "parse_error": None,
    }
    try:
        parsed = P.parse_trace(trace, observations)
        for col in P.COLUMN_KEYS:
            row[col] = parsed.get(col)
        row["derived"] = parsed["derived"]
        row["recognized_contract"] = parsed["recognized_contract"]
        row["parser_version"] = parsed["parser_version"]
    except Exception as e:  # defensive: never let one trace kill the batch
        logger.warning(
            "trace_parse_failed", trace_id=trace.get("id"), error=str(e)
        )
        row["parse_error"] = str(e)[:500]
        row["parser_version"] = P.PARSER_VERSION
        row["recognized_contract"] = None
    if is_singleton:
        # No predecessor: the turn "creates" any insight it carries and its whole
        # cumulative dataset list is new. Parse failures fall back to False / [].
        derived = row.get("derived") or {}
        row["insight_created_this_turn"] = row.get("insight_id") is not None
        row["datasets_analysed_this_turn"] = (
            derived.get("datasets_analysed_cumulative") or []
        )
    return _strip_nul(row)


# --------------------------------------------------------------------------- #
# Upsert
# --------------------------------------------------------------------------- #
async def _upsert(session: AsyncSession, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    keys: set[str] = set()
    for r in rows:
        keys.update(r.keys())
    stmt = pg_insert(LangfuseTraceOrm).values(rows)
    update_cols = {k: stmt.excluded[k] for k in keys if k != "id"}
    stmt = stmt.on_conflict_do_update(index_elements=["id"], set_=update_cols)
    await session.execute(stmt)
    return len(rows)


# Recompute the cross-row turn fields (turn_index, is_final_turn_in_thread, and the
# per-turn diffs) for the given sessions from current table state. Each depends on
# siblings, so a late/out-of-order trace can shift them; running once per chunk over
# the *full* touched session(s) on a single window keeps it deterministic (hence
# idempotent). Null-session singletons are set in build_row and never touched here.
_RECOMPUTE_SQL = text(
    """
    WITH ranked AS (
        SELECT id,
               row_number() OVER w AS rn,
               count(*)     OVER (PARTITION BY session_id) AS n,
               insight_id,
               lag(insight_id) OVER w AS prev_insight,
               ARRAY(SELECT jsonb_array_elements_text(
                   COALESCE(derived->'datasets_analysed_cumulative', '[]'::jsonb)
               )) AS cur_ds,
               lag(ARRAY(SELECT jsonb_array_elements_text(
                   COALESCE(derived->'datasets_analysed_cumulative', '[]'::jsonb)
               ))) OVER w AS prev_ds
        FROM langfuse_traces
        WHERE session_id = ANY(:ids)
        WINDOW w AS (
            PARTITION BY session_id
            ORDER BY trace_timestamp ASC NULLS LAST, id ASC
        )
    ),
    computed AS (
        SELECT id,
               rn AS turn_index,
               (rn = n) AS is_final,
               (insight_id IS NOT NULL
                AND insight_id IS DISTINCT FROM prev_insight) AS created,
               ARRAY(
                   SELECT unnest(cur_ds)
                   EXCEPT
                   SELECT unnest(COALESCE(prev_ds, ARRAY[]::text[]))
               )::varchar[] AS new_ds  -- match the column type for the guard below
        FROM ranked
    )
    UPDATE langfuse_traces t
    SET turn_index = c.turn_index,
        is_final_turn_in_thread = c.is_final,
        insight_created_this_turn = c.created,
        datasets_analysed_this_turn = c.new_ds
    FROM computed c
    WHERE t.id = c.id
      -- Skip rows already current: an UPDATE writes a new tuple even when nothing
      -- changed, so this guard avoids re-versioning every sibling each recompute.
      AND (t.turn_index                 IS DISTINCT FROM c.turn_index
        OR t.is_final_turn_in_thread    IS DISTINCT FROM c.is_final
        OR t.insight_created_this_turn  IS DISTINCT FROM c.created
        OR t.datasets_analysed_this_turn IS DISTINCT FROM c.new_ds)
    """
)


async def recompute_turn_positions(
    session: AsyncSession, session_ids: set[str]
) -> int:
    """Returns rows actually rewritten (0 when all sessions are already current)."""
    ids = [s for s in session_ids if s]
    if not ids:
        return 0
    result = await session.execute(_RECOMPUTE_SQL, {"ids": ids})
    return result.rowcount or 0


# Null-session rows are singleton threads with no predecessor: set their turn fields
# directly (mirrors build_row's singleton branch). Guarded like _RECOMPUTE_SQL so a
# re-run rewrites nothing.
_BACKFILL_SINGLETONS_SQL = text(
    """
    UPDATE langfuse_traces t
    SET turn_index = 1,
        is_final_turn_in_thread = true,
        insight_created_this_turn = c.created,
        datasets_analysed_this_turn = c.new_ds
    FROM (
        SELECT id,
               (insight_id IS NOT NULL) AS created,
               ARRAY(SELECT jsonb_array_elements_text(
                   COALESCE(derived->'datasets_analysed_cumulative', '[]'::jsonb)
               ))::varchar[] AS new_ds
        FROM langfuse_traces
        WHERE session_id IS NULL
    ) c
    WHERE t.id = c.id
      AND (t.turn_index                 IS DISTINCT FROM 1
        OR t.is_final_turn_in_thread    IS DISTINCT FROM true
        OR t.insight_created_this_turn  IS DISTINCT FROM c.created
        OR t.datasets_analysed_this_turn IS DISTINCT FROM c.new_ds)
    """
)

_DISTINCT_SESSIONS_SQL = text(
    "SELECT DISTINCT session_id FROM langfuse_traces WHERE session_id IS NOT NULL"
)


async def backfill_turn_fields(
    session: AsyncSession, *, batch_size: int = 500, dry_run: bool = False
) -> int:
    """One-off catch-up of the turn fields for rows predating the feature (new rows
    are set during ingest). Idempotent — reuses the no-op-guarded recompute, so a
    re-run writes 0 rows. Sessions are processed in committed batches to bound the
    transaction. Returns the number of rows that would be / were written.

    This is the out-of-band alternative to a migration backfill: run it manually after
    deploying (``backfill-turn-fields`` CLI command), not in the deploy path.
    """
    written = 0
    # Singletons first (independent of sessions), then each session renumbered.
    written += (await session.execute(_BACKFILL_SINGLETONS_SQL)).rowcount or 0
    session_ids = (
        (await session.execute(_DISTINCT_SESSIONS_SQL)).scalars().all()
    )
    for i in range(0, len(session_ids), batch_size):
        batch = set(session_ids[i : i + batch_size])
        written += await recompute_turn_positions(session, batch)
        if not dry_run:
            await session.commit()
    if dry_run:
        await session.rollback()
    else:
        await session.commit()  # covers the singleton-only case (no sessions)
    return written


# --------------------------------------------------------------------------- #
# Per-run metric accumulation
# --------------------------------------------------------------------------- #
@dataclass
class _Metrics:
    n_rows: int = 0
    fill_counts: dict[str, int] = field(
        default_factory=lambda: {c: 0 for c in MONITORED_COLS}
    )
    # soft-FK: key -> [present, resolved]
    fk: dict[str, list[int]] = field(
        default_factory=lambda: {
            "session_id": [0, 0],
            "user_id": [0, 0],
            "insight_id": [0, 0],
        }
    )
    contract_applicable: int = 0
    contract_bad: int = 0

    def add_rows(self, rows: list[dict[str, Any]]) -> None:
        self.n_rows += len(rows)
        for r in rows:
            for c in MONITORED_COLS:
                if r.get(c) is not None:
                    self.fill_counts[c] += 1
            rc = r.get("recognized_contract")
            if rc is not None:
                self.contract_applicable += 1
                if rc is False:
                    self.contract_bad += 1

    def fill_rates(self) -> dict[str, float]:
        if not self.n_rows:
            return {}
        return {
            c: round(self.fill_counts[c] / self.n_rows, 4)
            for c in MONITORED_COLS
        }

    def fk_resolve_rates(self) -> dict[str, float]:
        return {k: round(v[1] / v[0], 4) for k, v in self.fk.items() if v[0]}

    def unrecognized_rate(self) -> Optional[float]:
        if not self.contract_applicable:
            return None
        return round(self.contract_bad / self.contract_applicable, 4)


async def _count_existing(
    session: AsyncSession, table: str, col: str, ids: set[str]
) -> int:
    if not ids:
        return 0
    # table/col are fixed internal constants (not user input).
    sql = text(
        f"SELECT count(DISTINCT {col}) FROM {table} WHERE {col}::text = ANY(:ids)"
    )
    res = await session.execute(sql, {"ids": list(ids)})
    return int(res.scalar() or 0)


async def _accumulate_fk(
    session: AsyncSession, rows: list[dict[str, Any]], m: _Metrics
) -> None:
    """Best-effort soft-FK resolve-rate sampling. Never fails ingestion."""
    try:
        for key, (tbl, col) in {
            "session_id": ("threads", "id"),
            "user_id": ("users", "id"),
            "insight_id": ("insights", "id"),
        }.items():
            ids = {r[key] for r in rows if r.get(key)}
            if not ids:
                continue
            resolved = await _count_existing(session, tbl, col, ids)
            m.fk[key][0] += len(ids)
            m.fk[key][1] += resolved
    except Exception as e:  # monitoring must not break ingestion
        logger.warning("fk_resolve_sampling_failed", error=str(e))


# --------------------------------------------------------------------------- #
# Window ingestion
# --------------------------------------------------------------------------- #
@dataclass
class WindowStats:
    fetched: int = 0
    upserted: int = 0
    max_ts: Optional[datetime] = None
    # Session ids upserted this window; their turn positions are recomputed once
    # at the chunk boundary (see run_ingestion).
    touched_sessions: set[str] = field(default_factory=set)


async def ingest_window(
    session: AsyncSession,
    client: LangfuseClient,
    from_ts: datetime,
    to_ts: datetime,
    environment: Optional[str],
    metrics: _Metrics,
    *,
    batch_size: int = 300,
    dry_run: bool = False,
) -> WindowStats:
    """Fetch one closed window, parse, and upsert (chunked). The sync fetches run
    in a thread so they don't block the event loop. Fetch page size is clamped to
    the Langfuse list-page max (``MAX_PAGE_SIZE``); the upsert batch is independent."""
    page_size = min(batch_size, MAX_PAGE_SIZE)
    traces = await asyncio.to_thread(
        client.fetch_window, from_ts, to_ts, environment, page_size
    )
    traces, auxiliary = _split_auxiliary(traces)
    if auxiliary:
        logger.info(
            "langfuse_auxiliary_traces_skipped",
            window_start=from_ts.isoformat(),
            skipped=auxiliary,
        )
    obs_by_trace = await _fetch_observations(
        client,
        from_ts,
        to_ts,
        environment,
        page_size,
        {tid for t in traces if (tid := t.get("id"))},
    )
    stats = WindowStats(fetched=len(traces))
    batch: list[dict[str, Any]] = []
    for t in traces:
        trace_id = t.get("id")
        row = build_row(t, obs_by_trace.get(trace_id) if trace_id else None)
        if row["trace_timestamp"] is not None:
            if stats.max_ts is None or row["trace_timestamp"] > stats.max_ts:
                stats.max_ts = row["trace_timestamp"]
        batch.append(row)
        if len(batch) >= batch_size:
            await _flush(session, batch, metrics, stats, dry_run)
            batch = []
    if batch:
        await _flush(session, batch, metrics, stats, dry_run)
    return stats


def _split_auxiliary(
    traces: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Drop non-turn traces, returning (turns, dropped_count).

    An auxiliary trace is one LLM call made outside an agent turn — thread
    naming, area naming, language detection (see
    ``src.shared.langfuse_tracing.AUXILIARY_TAG``). It carries no AgentState, so
    ingesting it would add a zero-token EMPTY-outcome row and drag down every
    per-turn average. Its cost stays visible in Langfuse, under the same session
    id as the thread it belongs to.
    """
    turns = [t for t in traces if AUXILIARY_TAG not in (t.get("tags") or [])]
    return turns, len(traces) - len(turns)


async def _fetch_observations(
    client: LangfuseClient,
    from_ts: datetime,
    to_ts: datetime,
    environment: Optional[str],
    page_size: int,
    trace_ids: set[str],
) -> dict[str, list[dict[str, Any]]]:
    """This window's observations, grouped by trace id.

    Every observation type is fetched, not only the generations — see the
    comment on the fetch call. ``parse_observations`` picks the billable ones
    back out; the rest are the tree it needs to attribute them.

    Degrades rather than fails: on a fetch error the window still ingests, with
    token counts falling back to the message stream (agent-level only). The
    ``agent_tokens`` fill rate in the run row is what surfaces that.

    Observations belonging to traces outside ``trace_ids`` are dropped — the
    padded window necessarily catches children of traces that started earlier.
    """
    try:
        observations = await asyncio.to_thread(
            client.fetch_observations_window,
            from_ts,
            to_ts + OBSERVATION_WINDOW_PAD,
            environment,
            page_size,
            # Every type, not just generations: which component a generation
            # belongs to is written on its ANCESTORS (the LangGraph ``model``
            # chain, or the TOOL span above it), never on the generation
            # itself — both an agent call and a tool's call are named
            # "ChatGoogleGenerativeAI". Fetch generations alone and the parent
            # walk finds nothing, so every call lands in ``other`` and the
            # agent/tool split reads as all-tool.
            None,
        )
    except LangfuseFetchError as e:
        logger.error(
            "langfuse_observation_fetch_failed",
            window_start=from_ts.isoformat(),
            error=str(e),
        )
        return {}

    grouped: dict[str, list[dict[str, Any]]] = {}
    for o in observations:
        tid = o.get("traceId")
        if tid and tid in trace_ids:
            grouped.setdefault(tid, []).append(o)
    logger.info(
        "langfuse_observations_fetched",
        window_start=from_ts.isoformat(),
        observations=len(observations),
        traces_with_usage=len(grouped),
        traces=len(trace_ids),
    )
    return grouped


async def _flush(
    session: AsyncSession,
    batch: list[dict[str, Any]],
    metrics: _Metrics,
    stats: WindowStats,
    dry_run: bool,
) -> None:
    metrics.add_rows(batch)
    await _accumulate_fk(session, batch, metrics)
    if not dry_run:
        stats.upserted += await _upsert(session, batch)
        stats.touched_sessions.update(
            r["session_id"] for r in batch if r.get("session_id")
        )


# --------------------------------------------------------------------------- #
# Watermark + windows
# --------------------------------------------------------------------------- #
async def resolve_start_watermark(
    session: AsyncSession, environment: Optional[str]
) -> Optional[datetime]:
    stmt = select(func.max(LangfuseIngestionRunOrm.watermark)).where(
        LangfuseIngestionRunOrm.status.in_(("success", "partial"))
    )
    if environment:
        stmt = stmt.where(LangfuseIngestionRunOrm.environment == environment)
    res = await session.execute(stmt)
    return res.scalar()


def _chunks(
    since: datetime, until: datetime, chunk_hours: int
) -> Iterable[tuple[datetime, datetime]]:
    cur = since
    step = timedelta(hours=chunk_hours)
    while cur < until:
        nxt = min(cur + step, until)
        yield cur, nxt
        cur = nxt


# --------------------------------------------------------------------------- #
# Top-level run
# --------------------------------------------------------------------------- #
@dataclass
class RunResult:
    fetched: int = 0
    upserted: int = 0
    chunks_total: int = 0
    chunks_failed: int = 0
    status: str = "success"
    watermark: Optional[datetime] = None


async def run_ingestion(
    session: AsyncSession,
    *,
    since: datetime,
    until: datetime,
    environment: Optional[str] = None,
    chunk_hours: int = 24,
    batch_size: int = 300,
    dry_run: bool = False,
) -> RunResult:
    """Ingest [since, until) in ascending chunks, with one run row recording
    counts, watermark, and drift metrics. Aborts (status=partial) on the first
    chunk that fails after retries, leaving the watermark on the last good chunk.
    """
    client = LangfuseClient.from_env()
    run = LangfuseIngestionRunOrm(
        window_start=since,
        window_end=until,
        environment=environment,
        parser_version=P.PARSER_VERSION,
        status="running",
    )
    session.add(run)
    await session.flush()  # get run.id

    metrics = _Metrics()
    result = RunResult()

    for cfrom, cto in _chunks(since, until, chunk_hours):
        result.chunks_total += 1
        try:
            ws = await ingest_window(
                session,
                client,
                cfrom,
                cto,
                environment,
                metrics,
                batch_size=batch_size,
                dry_run=dry_run,
            )
        except LangfuseFetchError as e:
            logger.error(
                "ingest_chunk_failed",
                window_start=cfrom.isoformat(),
                error=str(e),
            )
            result.chunks_failed += 1
            result.status = "partial"
            break
        result.fetched += ws.fetched
        result.upserted += ws.upserted
        if not dry_run:
            # Renumber turn positions for touched sessions from current table
            # state, in-transaction, before the chunk is committed.
            await recompute_turn_positions(session, ws.touched_sessions)
            await session.commit()  # persist chunk before advancing watermark
        result.watermark = cto  # contiguous advance
        logger.info(
            "ingest_chunk_done",
            window_start=cfrom.isoformat(),
            fetched=ws.fetched,
            upserted=ws.upserted,
        )

    run.finished_at = _utcnow()
    run.traces_fetched = result.fetched
    run.traces_upserted = result.upserted
    run.chunks_total = result.chunks_total
    run.chunks_failed = result.chunks_failed
    run.status = result.status if not dry_run else "success"
    run.watermark = result.watermark
    run.fill_rates = metrics.fill_rates()
    run.fk_resolve_rates = metrics.fk_resolve_rates()
    run.unrecognized_contract_rate = metrics.unrecognized_rate()
    if not dry_run:
        await session.commit()
    return result
