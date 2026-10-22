"""gold: run GOLD cases against a live GNW agent API and record the results.

Examples:
  gold run --env staging --trials 3
  gold run --api-base-url https://api.staging.globalnaturewatch.org --id 1-030
  gold run --resume <run_id>
  gold prune-artifacts --keep-runs 5

Each run writes one run record under results/runs/. The profile, trial and
smoke-run rules are in README.md, "Running the set".

Flags always win: no environment variable changes a flag or its default.
The environment (or a .env file) supplies secrets only:
  STAGING_API_TOKEN, PROD_API_TOKEN  API token for that environment. API_TOKEN
                                     is the fallback, and the only one a local
                                     run reads.
  ANTHROPIC_API_KEY                  the LLM judge (the default backend)
  OPENROUTER_API_KEY                 the LLM judge under
                                     --judge-backend openrouter-jev-decisions
  ANALYTICS_API_TOKEN                ground-truth fetches from the analytics
                                     API; the run's API token if unset
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from goldset.adapter import case_to_expected
from goldset.buckets import row_verdict, summarize_buckets
from goldset.eval_types import TestResult
from goldset.judge_config import (
    DEFAULT_JUDGE_BACKEND,
    JUDGE_BACKEND_CHOICES,
    JUDGE_BACKEND_ENV_VAR,
    judge_model_for_backend,
)
from goldset.ledger import (
    RUNS_DIRNAME,
    append_partial_entry,
    majority,
    make_run_id,
    partial_path,
    read_partial,
    reason_name_from_column,
    write_partial_header,
    write_run,
)
from goldset.store import Case, load_store, read_manifest
from goldset.templates import resolve_templates

ENV_URLS = {
    "staging": "https://api.staging.globalnaturewatch.org",
    "prod": "https://api.globalnaturewatch.org",
    "local": "http://localhost:8000",
}
NON_CHECK_SCORES = {"overall_score"}
REASON_TRIM = 500
ENV_TOKEN_VARS = {"staging": "STAGING_API_TOKEN", "prod": "PROD_API_TOKEN"}


def require_api_token(environment: str) -> str | None:
    """Prefer the env-specific token (STAGING_API_TOKEN, PROD_API_TOKEN),
    fall back to API_TOKEN; print what was missing when neither is set."""
    env_var = ENV_TOKEN_VARS.get(environment)
    token = (env_var and os.environ.get(env_var)) or os.environ.get("API_TOKEN")
    if not token:
        candidates = f"{env_var} or API_TOKEN" if env_var else "API_TOKEN"
        print(f"{candidates} is not set (environment-specific machine token)")
    return token


# Which actual_* diagnostics substantiate each check. They are recorded on
# the entry for FAILED checks only, so reports can show expected against
# measured without re-running anything.
ACTUALS_FOR_CHECK = {
    "aoi_id_match": ("actual_id",),
    "dataset_id_match": ("actual_dataset_id",),
    "dataset_parameter_match": ("actual_dataset_parameters",),
    "context_layer_match": ("actual_context_layer",),
    "date_extraction": ("actual_extracted_start_date", "actual_extracted_end_date"),
    "date_coverage": ("actual_start_date", "actual_end_date"),
    "data_pull_exists": ("data_pull_error",),
    "agent_answer": ("actual_agent_answer",),
    "charts_answer": ("actual_charts_answer",),
    "expected_text_match": ("actual_agent_answer",),
    "clarification_requested": ("actual_clarification_requested",),
    "suggested_datasets_match": ("actual_suggested_datasets",),
    "nudge_match": ("actual_nudge_type", "actual_nudge_options"),
    "chart_type_match": ("actual_chart_type",),
    "scope_match": ("actual_scope",),
    "class_value_match": ("actual_class_values",),
    "answer_traceability": ("actual_traceability_claim",),
    "dashboard_created": ("actual_dashboard_created",),
    "dashboard_aoi_match": ("actual_dashboard_aoi_id", "actual_dashboard_aoi_count"),
    "dashboard_widgets_match": ("actual_dashboard_widget_types",),
    "web_fallback": ("actual_web_links",),
    "pull_source_match": ("actual_pull_source",),
    "ground_truth_match": ("agent_ground_truth",),
    "ground_truth_answer": ("agent_ground_truth_answer",),
}
ACTUAL_TRIM = 300


def _failed_actuals(dumped: dict, checks: dict) -> dict:
    actuals = {}
    for check, value in checks.items():
        if value != 0.0:
            continue
        parts = [
            str(dumped[field])
            for field in ACTUALS_FOR_CHECK.get(check, ())
            if dumped.get(field) not in (None, "")
        ]
        if parts:
            actuals[check] = " · ".join(parts)[:ACTUAL_TRIM]
    return actuals


def result_to_entry(result: TestResult, uid: str) -> dict:
    """Map one TestResult to one ledger entry (single trial)."""
    dumped = result.model_dump()
    checks = {
        key.removesuffix("_score"): value
        for key, value in dumped.items()
        if key.endswith("_score") and key not in NON_CHECK_SCORES
    }
    reasons = {}
    for key, value in dumped.items():
        check = reason_name_from_column(key)
        if check and value:
            reasons[check] = str(value)[:REASON_TRIM]

    entry: dict = {"uid": uid, "id": result.test_id, "checks": checks}
    if reasons:
        entry["reasons"] = reasons
    actuals = _failed_actuals(dumped, checks)
    if actuals:
        entry["actuals"] = actuals
    judge_errors = dumped.get("judge_errors") or []
    if judge_errors:
        entry["judge_errors"] = judge_errors
    if result.duration_seconds is not None:
        entry["latency_s"] = round(result.duration_seconds, 1)
    if result.trace_url:
        entry["trace_url"] = result.trace_url
    if result.error:
        entry["error"] = str(result.error)[:REASON_TRIM]
    return entry


def latency_info(latency_s: float | None, slow_threshold: float) -> dict | None:
    """Info-only "slow" flag for a merged entry: recorded, never scored.

    Returns None (so no ``info`` key is written) when the latency is at or
    under the threshold, or was not recorded.
    """
    if latency_s is None or latency_s <= slow_threshold:
        return None
    return {"slow": True, "threshold_s": slow_threshold}


def merge_trials(entries: list[dict]) -> dict:
    """Fold per-trial entries into one: majority verdict + per-trial detail."""
    if len(entries) == 1:
        return entries[0]
    merged = dict(entries[-1])
    check_names = sorted({name for e in entries for name in e["checks"]})
    merged["checks"] = {
        name: majority([e["checks"].get(name) for e in entries]) for name in check_names
    }
    merged["trials"] = [
        {"checks": e["checks"], "latency_s": e.get("latency_s")} for e in entries
    ]
    # Errors from ANY trial must survive the merge: the base copy above only
    # carries the final trial's metadata.
    judge_errors = sorted({je for e in entries for je in e.get("judge_errors", [])})
    if judge_errors:
        merged["judge_errors"] = judge_errors
    else:
        merged.pop("judge_errors", None)
    errors = list(dict.fromkeys(e["error"] for e in entries if e.get("error")))
    if errors:
        merged["error"] = " | ".join(errors)[:500]
    else:
        merged.pop("error", None)
    return merged


def _harness_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=Path(__file__).resolve().parents[2],
        ).stdout.strip()
    except (subprocess.CalledProcessError, OSError):
        return "unknown"


def select_cases(args: argparse.Namespace) -> list[Case]:
    excluded = {s.strip().lower() for s in args.status_exclude.split(",") if s.strip()}
    cases = [case for _path, case, _uid in load_store(args.cases_dir)]
    cases = [c for c in cases if c.status.lower() not in excluded]
    if args.id:
        wanted = {i.lower() for i in args.id}
        cases = [c for c in cases if c.id.lower() in wanted]
    if args.group:
        cases = [c for c in cases if args.group.lower() in c.group.lower()]
    # Start multi-turn cases first: they take longest, and if started last (as
    # 'mt-' sorts after '1-') they leave a long tail at the end of the run.
    return sorted(cases, key=lambda c: (not c.is_multiturn, c.id))


async def run_cases(
    args: argparse.Namespace,
    cases: list[Case],
    entry_sink=None,
) -> list[dict]:
    # Deferred import: langchain/httpx stay out of store-only invocations.
    from goldset.groundtruth.client import agent_environment
    from goldset.runner.api import APITestRunner
    from goldset.runner.artifacts import ArtifactWriter
    from goldset.runner.multiturn import run_conversation

    runner = APITestRunner(
        api_base_url=args.resolved_url,
        api_token=args.api_token,
        ff=args.ff,
        verbose=args.verbose,
        wall_clock_limit=args.trial_timeout,
        # Only ground-truth cases re-read the agent's pull, so this stays None
        # for a run with none and no extra request is ever issued.
        analytics_token=(
            (os.environ.get("ANALYTICS_API_TOKEN") or os.environ.get("API_TOKEN"))
            if args.ground_truth
            else None
        ),
        # That re-read fetches a result the agent created, so it asks for the
        # environment the agent ran in. Ground truth stays on production.
        analytics_environment=agent_environment(getattr(args, "environment", "")),
    )
    writer = ArtifactWriter(args.results_dir / "artifacts", args.run_id)
    # Hard cap on concurrency against the live API (20 is known to run cleanly).
    semaphore = asyncio.Semaphore(max(1, min(args.workers, 20)))

    run_started = datetime.now()
    total_cases = len(cases)
    completed_cases = 0

    def _resolve_case(case: Case) -> Case:
        """Expand template variables in queries. ``replace`` carries every
        other field over, including the store's uid_includes_deltas rule. The
        result hashes to a new uid if a query was templated, so run_one records
        the stored case's uid (``original_uid``)."""
        if case.is_multiturn:
            resolved_turns = tuple(
                {**turn, "query": resolve_templates(turn["query"], now=run_started)}
                for turn in case.turns
            )
            return dataclasses.replace(case, turns=resolved_turns)
        return dataclasses.replace(
            case, query=resolve_templates(case.query, now=run_started)
        )

    async def run_one(case: Case) -> dict:
        nonlocal completed_cases
        async with semaphore:
            original_uid = case.uid
            resolved = _resolve_case(case)
            trials = []
            agent_values = []  # per trial: the agent's own figures, ground truth only
            for trial in range(1, args.trials + 1):
                if resolved.is_multiturn:
                    entry = await run_conversation(
                        runner,
                        resolved,
                        result_to_entry,
                        artifact_sink_factory=lambda n, c=case, t=trial: (
                            lambda a: writer(f"{c.uid}_turn{n}", t, a)
                        ),
                    )
                    entry["uid"] = original_uid
                    trials.append(entry)
                else:
                    result = await runner.run_test(
                        # `resolved` carries the template-expanded query;
                        # expectations and the ground-truth key come from the
                        # ORIGINAL case, whose uid is what prefetch keyed on
                        # (resolving mints a different query, hence a different
                        # uid — the same reason original_uid is captured above).
                        resolved.query,
                        case_to_expected(case, args.ground_truth.get(case.uid)),
                        artifact_sink=lambda a, c=case, t=trial: writer(c.uid, t, a),
                    )
                    trials.append(result_to_entry(result, original_uid))
                    agent_values.append(result.agent_ground_truth_values)
            entry = merge_trials(trials)
            # One fetch serves every trial, so the record sits on the merged
            # entry; attached before entry_sink so a resume keeps it.
            ground_truth = args.ground_truth.get(original_uid)
            if ground_truth is not None:
                entry["ground_truth"] = {
                    **ground_truth.to_ledger(),
                    # aligned with `trials`: what the agent's pull gave each time
                    "agent_values": agent_values,
                }
            # Slow rows get an info flag: recorded, never scored.
            info = latency_info(entry.get("latency_s"), args.slow_threshold)
            if info:
                entry["info"] = info
            if entry_sink is not None:
                entry_sink(entry)
            # Use row_verdict, as the ledger and reports do, so an info-only
            # check scoring 0.0 does not print FAIL.
            verdict = row_verdict(entry)
            label = {"fail": "FAIL", "error": "ERROR"}.get(verdict, "ok")
            # status rides along so a FAIL on an unverified (ready/todo) case
            # reads differently from a FAIL on a verified (done) one.
            completed_cases += 1
            # flush: through a pipe, block buffering can hold every progress
            # line until exit, which is exactly when a killed run needs them.
            print(
                f"  {case.id} [{label}] status={case.status} "
                f"({completed_cases}/{total_cases})",
                flush=True,
            )
            return entry

    return list(await asyncio.gather(*(run_one(case) for case in cases)))


def build_run_record(
    args: argparse.Namespace,
    manifest: dict,
    entries: list[dict],
    started: str,
    environment: str,
) -> dict:
    """The ledger record for a finished run (contract: results/README.md).

    ``caseset`` names the store directory the run loaded (``v1``/``v2``),
    because ``caseset_version`` alone is a content hash a reader cannot trace
    to a store without digging through git history. Runs before 2026-08-04
    lack the field.
    """
    judge_backend = getattr(args, "judge_backend", DEFAULT_JUDGE_BACKEND)
    record = {
        "run_id": args.run_id,
        "started": started,
        "environment": environment,
        "build": args.build,
        "ff": args.ff,
        "harness": {"repo": "gnw-gold-evals", "sha": _harness_sha()},
        "judge_model": judge_model_for_backend(judge_backend),
        "num_trials": args.trials,
        "workers": args.workers,
        "trial_timeout": args.trial_timeout,
        "caseset": args.cases_dir.name,
        "caseset_version": manifest["caseset_version"],
        "results": entries,
        "buckets": summarize_buckets(entries),
    }
    ground_truth_cases = sum(1 for entry in entries if "ground_truth" in entry)
    if ground_truth_cases:
        from goldset.evaluators.llm_judges import NUMERIC_TOLERANCE

        record["ground_truth"] = {
            "base_url": args.analytics_base_url,
            "cases": ground_truth_cases,
            "prefetch_seconds": getattr(args, "prefetch_seconds", None),
            "tolerance": NUMERIC_TOLERANCE,
        }
    if args.note:
        return {**record, "methodology_note": args.note}
    return record


def _finalise(
    args: argparse.Namespace,
    manifest: dict,
    entries: list[dict],
    started: str,
    environment: str,
    partial: Path,
    resumed: bool,
) -> int:
    """Write the immutable run record and retire the in-flight partial."""
    entries = sorted(entries, key=lambda e: e["id"])
    run_record = build_run_record(args, manifest, entries, started, environment)
    if resumed:
        run_record["resumed"] = True
    path = write_run(args.results_dir, run_record)
    partial.unlink()
    # Use row_verdict so an info-only check scoring 0.0 does not count as a failure.
    failed = sum(1 for e in entries if row_verdict(e) == "fail")
    errored = sum(1 for e in entries if row_verdict(e) == "error")
    line = f"wrote {path} — {len(entries)} cases, {failed} with failing checks"
    if errored:
        line += f", {errored} with ERRORS (rerun before trusting)"
    print(line)
    return 0


def prefetch_ground_truth(args: argparse.Namespace, cases: list[Case]) -> bool:
    """Resolve every ground-truth case before any trial. False means abort.

    Runs before the in-flight partial header is written, so a failed prefetch
    leaves no partial file behind — nothing has been sent to the agent and
    there is no half-run to mislead a reader. Sets ``args.ground_truth`` (empty
    when no case carries a selector), which ``run_cases`` reads per case.

    Called from both entry points: a resumed run's remaining cases include
    ground-truth ones, and they need values just as much as a fresh run's.
    Re-fetching on resume is correct — the run already spans two sessions, and
    the alternative is grading the remainder against nothing.
    """
    from goldset.groundtruth import (
        AnalyticsError,
        RequestError,
        SelectorError,
        prefetch,
    )
    from goldset.groundtruth.client import BASE_URL, AnalyticsClient
    from goldset.groundtruth.fetch import is_ground_truth

    args.ground_truth = {}
    args.analytics_base_url = getattr(args, "analytics_base_url", None) or BASE_URL
    targets = [case for case in cases if is_ground_truth(case)]
    if not targets:
        return True

    client = AnalyticsClient(
        token=os.environ.get("ANALYTICS_API_TOKEN") or args.api_token,
        base_url=args.analytics_base_url,
    )
    print(
        f"prefetch: {len(targets)} ground-truth case(s) "
        f"from {args.analytics_base_url}",
        flush=True,
    )
    started_fetch = time.monotonic()
    try:
        args.ground_truth = prefetch(targets, client, verbose=args.verbose)
    except (RequestError, AnalyticsError, SelectorError) as error:
        print(f"  ABORT — ground-truth prefetch failed: {error}", flush=True)
        return False
    elapsed = round(time.monotonic() - started_fetch, 1)
    args.prefetch_seconds = round(
        (getattr(args, "prefetch_seconds", None) or 0.0) + elapsed, 1
    )
    unresolved = [g for g in args.ground_truth.values() if g.unresolved]
    line = (
        f"  resolved {len(args.ground_truth) - len(unresolved)}"
        f"/{len(targets)} in {elapsed}s"
    )
    if unresolved:
        line += f" — {len(unresolved)} unresolved, will ERROR: " + ", ".join(
            g.case_id for g in unresolved
        )
    print(line, flush=True)
    return True


def resume_run(args: argparse.Namespace) -> int:
    """Finish a killed run from its in-flight partial file.

    All run configuration comes from the partial's header. Flags on the
    resume invocation are ignored, except ``--results-dir``, which locates
    the partial, and ``--verbose``. The final record matches an unbroken run
    apart from a ``resumed: true`` marker (its timing mixes two sessions).
    """
    partial = partial_path(args.results_dir, args.resume)
    final = args.results_dir / RUNS_DIRNAME / f"{args.resume}.json"
    if not partial.exists():
        state = "is already finalised" if final.exists() else "has no partial file"
        print(f"run {args.resume} {state}; nothing to resume")
        return 1
    header, done = read_partial(partial)
    if final.exists():
        # killed between write_run and unlink: the run is complete
        print(f"{final} already exists — removing the stale partial")
        partial.unlink()
        return 0

    args.cases_dir = Path(header["cases_dir"])
    manifest = read_manifest(args.cases_dir)
    if manifest is None:
        print(f"no manifest under {args.cases_dir}")
        return 1
    if manifest["caseset_version"] != header["caseset_version"]:
        print(
            "caseset_version has changed since the run started "
            f"({header['caseset_version']} -> {manifest['caseset_version']}); "
            "a run must score one case set — start a fresh run instead"
        )
        return 1
    for field in (
        "ff",
        "build",
        "trials",
        "workers",
        "trial_timeout",
        "slow_threshold",
        "status_exclude",
        "id",
        "group",
        "note",
    ):
        setattr(args, field, header[field])
    args.judge_backend = header.get(
        "judge_backend",
        getattr(args, "judge_backend", DEFAULT_JUDGE_BACKEND),
    )
    args.run_id = header["run_id"]
    args.resolved_url = header["resolved_url"]
    # .get(): partials written before ground truth lacked both, and must still
    # resume (None falls back to the default host and a zero timing).
    args.analytics_base_url = header.get("analytics_base_url")
    args.prefetch_seconds = header.get("prefetch_seconds")

    load_dotenv()

    args.environment = header["environment"]
    args.api_token = require_api_token(args.environment)
    if not args.api_token:
        return 1
    os.environ[JUDGE_BACKEND_ENV_VAR] = args.judge_backend

    done_uids = {entry["uid"] for entry in done}
    remaining = [c for c in select_cases(args) if c.uid not in done_uids]
    print(
        f"resume {args.run_id}: {len(done)} case(s) already scored, "
        f"{len(remaining)} remaining against {args.resolved_url}",
        flush=True,
    )
    if not prefetch_ground_truth(args, remaining):
        return 1
    new_entries = (
        asyncio.run(
            run_cases(
                args,
                remaining,
                entry_sink=lambda e: append_partial_entry(partial, e),
            )
        )
        if remaining
        else []
    )
    return _finalise(
        args,
        manifest,
        done + new_entries,
        header["started"],
        header["environment"],
        partial,
        resumed=True,
    )


def prune_artifacts(results_dir: Path, keep_runs: int) -> int:
    """Artefacts are uncommitted and grow without limit: keep the newest N run
    directories (run_ids sort chronologically) and delete the rest. A pruned
    run can no longer be re-analysed from raw state; its ledger record stays."""
    import shutil

    artifacts = results_dir / "artifacts"
    if not artifacts.exists():
        print("no artifacts directory; nothing to prune")
        return 0
    run_dirs = sorted(d for d in artifacts.iterdir() if d.is_dir())
    doomed = run_dirs[:-keep_runs] if keep_runs > 0 else run_dirs
    for directory in doomed:
        shutil.rmtree(directory)
        print(f"pruned {directory}")
    print(f"kept {len(run_dirs) - len(doomed)} run(s), pruned {len(doomed)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="gold",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run cases against a live API")
    run.add_argument("--env", choices=sorted(ENV_URLS), default="staging")
    run.add_argument(
        "--api-base-url", default=None, help="explicit URL; overrides --env"
    )
    run.add_argument(
        "--ff",
        default=None,
        help="agent tool profile (the ff feature flag sent with each "
        "chat request). Omit it for the default profile, which "
        "is enough for a trusted run; pass 'experimental' only "
        "to test features still behind it. Never diff runs "
        "made with different --ff.",
    )
    run.add_argument(
        "--judge-backend",
        choices=JUDGE_BACKEND_CHOICES,
        default=DEFAULT_JUDGE_BACKEND,
        help=(
            "judge backend: default Anthropic Haiku, or TypeSafe JEV via "
            "OpenRouter Decisions"
        ),
    )
    run.add_argument(
        "--build", default="unknown", help="agent build label, e.g. 'GNW 2026.7.29.1'"
    )
    run.add_argument(
        "--trials",
        type=int,
        default=1,
        help="trials per case; each check keeps its majority verdict "
        "(ties fail). Use 3 for any run you will diff or keep "
        "as a baseline; 1, the default, is a smoke run.",
    )
    # Concurrency is recorded on the run (the ledger's `workers` field): a burst
    # of timeouts late in a run usually means load, and that cannot be diagnosed
    # without knowing the concurrency.
    run.add_argument("--workers", type=int, default=10)
    run.add_argument("--status-exclude", default="not doing")
    run.add_argument(
        "--id", action="append", default=None, help="run only this case id (repeatable)"
    )
    run.add_argument("--group", default=None, help="substring match on group")
    run.add_argument("--cases-dir", type=Path, default=Path("cases/v2"))
    run.add_argument("--results-dir", type=Path, default=Path("results"))
    run.add_argument(
        "--slow-threshold",
        type=float,
        default=180.0,
        help="seconds; slower rows get an info flag (never scored)",
    )
    run.add_argument(
        "--trial-timeout",
        type=float,
        default=900.0,
        help="hard per-trial time limit in seconds; a trial that "
        "exceeds it is recorded as an error",
    )
    run.add_argument(
        "--note",
        default=None,
        help="methodology note recorded on the run (e.g. after a "
        "check-semantics change, so diffs aren't read as agent movement)",
    )
    run.add_argument(
        "--analytics-base-url",
        default=None,
        help="analytics API host used to fetch ground truth",
    )
    run.add_argument(
        "--dry-run",
        action="store_true",
        help="list selected cases without calling the API",
    )
    run.add_argument(
        "--resume",
        default=None,
        metavar="RUN_ID",
        help="finish a killed run from its .partial.jsonl. The "
        "run's settings come from that file, so other flags "
        "are ignored, except --results-dir (which must match "
        "the original run) and --verbose.",
    )
    run.add_argument("--verbose", action="store_true")

    prune = sub.add_parser(
        "prune-artifacts",
        help="delete raw artifact dirs beyond the newest N runs (ledger is untouched)",
    )
    prune.add_argument("--results-dir", type=Path, default=Path("results"))
    prune.add_argument("--keep-runs", type=int, default=5)
    args = parser.parse_args()

    if args.command == "prune-artifacts":
        return prune_artifacts(args.results_dir, args.keep_runs)

    if args.resume:
        return resume_run(args)

    manifest = read_manifest(args.cases_dir)
    if manifest is None:
        print(f"no manifest under {args.cases_dir}")
        return 1
    cases = select_cases(args)
    if not cases:
        print("no cases selected")
        return 1
    if args.dry_run:
        for case in cases:
            preview = case.query or (
                f"({len(case.turns)} turns) " + case.turns[0]["query"]
            )
            print(f"{case.id}  {case.uid}  [{case.status}] {preview[:70]}")
        print(f"{len(cases)} cases selected (dry run)")
        return 0
    # Secrets may live in .env. Loaded here, before the token check, and used
    # only for secrets: the environment never overrides a CLI default.
    load_dotenv()

    args.resolved_url = args.api_base_url or ENV_URLS[args.env]
    if not args.api_base_url:
        environment = args.env
    elif "staging" in args.api_base_url:
        environment = "staging"
    elif any(h in args.api_base_url for h in ("localhost", "127.0.0.1", "0.0.0.0")):
        environment = "local"
    else:
        environment = "prod"
    args.environment = environment

    args.api_token = require_api_token(environment)
    if not args.api_token:
        return 1
    os.environ[JUDGE_BACKEND_ENV_VAR] = args.judge_backend
    started = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    args.run_id = make_run_id(started, environment, args.ff)

    # Before the partial header is written: a failed prefetch must leave no
    # partial file, and nothing has been sent to the agent yet.
    if not prefetch_ground_truth(args, cases):
        return 1

    partial = write_partial_header(
        args.results_dir,
        {
            "run_id": args.run_id,
            "started": started,
            "environment": environment,
            "resolved_url": args.resolved_url,
            "ff": args.ff,
            "judge_backend": args.judge_backend,
            "build": args.build,
            "trials": args.trials,
            "workers": args.workers,
            "trial_timeout": args.trial_timeout,
            "slow_threshold": args.slow_threshold,
            "cases_dir": str(args.cases_dir),
            "caseset_version": manifest["caseset_version"],
            "status_exclude": args.status_exclude,
            "id": args.id,
            "group": args.group,
            "note": args.note,
            "analytics_base_url": args.analytics_base_url,
            "prefetch_seconds": getattr(args, "prefetch_seconds", None),
        },
    )

    print(
        f"run {args.run_id}: {len(cases)} cases x {args.trials} trial(s) "
        f"against {args.resolved_url}",
        flush=True,
    )
    print(
        f"  in-flight ledger: {partial} "
        f"(if killed: gold run --resume {args.run_id})",
        flush=True,
    )
    entries = asyncio.run(
        run_cases(
            args,
            cases,
            entry_sink=lambda e: append_partial_entry(partial, e),
        )
    )
    return _finalise(
        args, manifest, entries, started, environment, partial, resumed=False
    )


if __name__ == "__main__":
    sys.exit(main())
