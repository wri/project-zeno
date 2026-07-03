"""Orchestrate Langfuse trace ingestion into Postgres.

Fetch a closed time window (ascending), parse each trace against the AgentState
contract, idempotently upsert rows, and record a ``langfuse_ingestion_runs`` row
with watermark + drift-observability metrics (fill rates, soft-FK resolve rates,
unrecognized-contract rate).

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
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

# Langfuse caps list page size (a 300 request 400s); 50 is proven-safe.
MAX_PAGE_SIZE = 50

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
def build_row(trace: dict[str, Any]) -> dict[str, Any]:
    """Map a trace to a langfuse_traces (derived analytics) row dict. Parse
    failures still yield a row (identity + parse_error) so one bad trace never
    aborts the batch."""
    session_id = trace.get("sessionId")
    # Null-session traces are singleton threads (COALESCE(session_id, id)); set
    # their turn position directly. Session-scoped rows get it from the post-upsert
    # recompute (cross-row), so they carry None here to be filled in-transaction.
    is_singleton = session_id is None
    row: dict[str, Any] = {
        "id": trace.get("id"),
        "session_id": session_id,
        "user_id": trace.get("userId"),
        "environment": trace.get("environment"),
        "trace_timestamp": _parse_dt(trace.get("timestamp")),
        "trace_updated_at": _parse_dt(trace.get("updatedAt")),
        "latency_seconds": trace.get("latency"),
        "total_cost": trace.get("totalCost"),
        # Turn position + per-turn diffs are cross-row: session rows carry None and
        # are filled by the post-upsert recompute; singletons are set below.
        "turn_index": 1 if is_singleton else None,
        "is_final_turn_in_thread": True if is_singleton else None,
        "insight_created_this_turn": None,
        "datasets_analysed_this_turn": None,
        "parsed_at": _utcnow(),
        "parse_error": None,
    }
    try:
        parsed = P.parse_trace(trace)
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
        # No predecessor: a singleton turn "creates" any insight it carries, and
        # its whole cumulative dataset list is new this turn. Parse-failure rows
        # (no insight_id / derived) fall back to False / empty.
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


# Recompute the cross-row turn fields for the given sessions from current table
# state: turn_index / is_final_turn_in_thread (position) plus the per-turn diffs
# insight_created_this_turn / datasets_analysed_this_turn (this turn vs. the prior
# one). All depend on siblings (a new/late/out-of-order trace shifts ordinals and
# the neighbouring diffs), so it runs once per chunk over the *full* touched
# session(s), not per batch, on a single window. Deterministic -> re-ingesting a
# window is idempotent. Null-session rows are singleton threads set in build_row
# and never touched here.
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
    )
    UPDATE langfuse_traces t
    SET turn_index = ranked.rn,
        is_final_turn_in_thread = (ranked.rn = ranked.n),
        insight_created_this_turn =
            (ranked.insight_id IS NOT NULL
             AND ranked.insight_id IS DISTINCT FROM ranked.prev_insight),
        datasets_analysed_this_turn = ARRAY(
            SELECT unnest(ranked.cur_ds)
            EXCEPT
            SELECT unnest(COALESCE(ranked.prev_ds, ARRAY[]::text[]))
        )
    FROM ranked
    WHERE t.id = ranked.id
    """
)


async def recompute_turn_positions(
    session: AsyncSession, session_ids: set[str]
) -> None:
    ids = [s for s in session_ids if s]
    if not ids:
        return
    await session.execute(_RECOMPUTE_SQL, {"ids": ids})


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
    """Fetch one closed window, parse, and upsert (chunked). The sync fetch runs
    in a thread so it doesn't block the event loop. Fetch page size is clamped to
    the Langfuse API max (100); the upsert batch size is independent."""
    page_size = min(batch_size, MAX_PAGE_SIZE)
    traces = await asyncio.to_thread(
        client.fetch_window, from_ts, to_ts, environment, page_size
    )
    stats = WindowStats(fetched=len(traces))
    batch: list[dict[str, Any]] = []
    for t in traces:
        row = build_row(t)
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
