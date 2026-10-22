# Results ledger: contract

Terms are defined in the [README glossary](../README.md#glossary).

`results/runs/` holds one committed JSON file per run: the long-term record
GOLD exists to keep. `gold run` writes these files. A couple of the oldest
runs here were converted from the earlier gnw-evals harness by a
since-retired import tool; their `harness.repo` reads `"gnw-evals"` rather
than `"gnw-gold-evals"`, and they carry the `stale_case`/`drift`/`joined_by`
fields documented below, which no current tool writes. Raw per-case agent
state goes to `results/artifacts/` (gitignored), rendered reports to
`results/reports/`, and the written analysis of each official run to
`results/recommendations/`.

## File naming

```
results/runs/<YYYYMMDD>T<HHMMSS>Z_<env>[_<ff>].json
```

The time is the run's start in UTC. The `_<ff>` suffix is left out when the
run used the agent's default profile, so a `_prod` run and a
`_prod_experimental` run used different profiles.

## Shape

Trimmed from `results/runs/20260831T163347Z_prod.json`:

```jsonc
{
  "run_id": "20260831T163347Z_prod",
  "started": "2026-08-31T16:33:47Z",     // UTC
  "environment": "prod",                 // staging | prod | local
  "build": "baseline",                   // the --build label (default "unknown")
  "ff": null,                            // agent tool profile; null = default
  "harness": {"repo": "gnw-gold-evals", "sha": "28941a8"},
  "judge_model": "claude-haiku-4-5",     // or "typesafe/jev-1.13" (--judge-backend)
  "num_trials": 3,
  "workers": 10,                         // concurrency, to trace timeouts to load
  "trial_timeout": 900.0,                // per-trial wall-clock limit, seconds
  "caseset": "v2",                       // store loaded: cases/<caseset>
  "caseset_version": "bf5a593d71d658ae", // that store's MANIFEST.json at run time
  "results": [
    {
      "uid": "6c8b9a9d674922d2",         // the exact case version scored
      "id": "1-005",                     // lineage id, for humans
      "checks": {                        // every check: 1.0 | 0.0 | null
        "aoi_id_match": 1.0,             // (the majority verdict when trials > 1)
        "dataset_id_match": 0.0,
        "date_extraction": null,
        ...
      },
      "reasons": {                       // any check that explained its score,
        "answer_traceability":           // trimmed to 500 characters
          "deterministic check: the chart's closest figure to the expected ..."
      },
      "actuals": {                       // failed checks only: the measured value,
        "dataset_id_match": "11"         // so reports show expected vs measured
      },
      "latency_s": 126.2,
      "trace_url": "https://langfuse.globalnaturewatch.org/project/wri_lcl/traces/...",
      "trials": [                        // trials > 1 only: each trial's own checks
        {"checks": {"aoi_id_match": 1.0, "dataset_id_match": 0.0, ...}, "latency_s": 17.0},
        {"checks": {...}, "latency_s": 20.7},
        {"checks": {...}, "latency_s": 126.2}
      ]
    }
  ],
  "buckets": {                           // per-bucket tallies that reports render
    "retrieval": {"dedicated": {"passed": 407, "evaluated": 438},
                  "shared": {"passed": 0, "evaluated": 0},
                  "rows_covered": 103},
    ...                                  // analysis, explanation, output, scope
    "rows_total": 109,
    "verdicts": {"pass": 94, "fail": 15, "error": 0, "uncovered": 0}
  }
}
```

A ground-truth case (one with `expected.ground_truth`) adds an object to
its entry, and the run gains a summary:

```jsonc
// on the entry
"ground_truth": {
  "selector": "sum(carbon_emissions_MgCO2e) WHERE tree_cover_loss_year=2019",
  "values": [658496.56],            // fetched at run start, one fetch per run
  "digest": "…",                    // absent when `unresolved` is set
  "dataset_id": "4",
  "content_date_fixed": false,
  "resource_id": "09272a7f-…",
  "fetched_at": "2026-09-14T12:00:05Z",
  "request": {"endpoint": "/v0/land_change/tree_cover_loss/analytics",
              "payload": {"aoi": {"type": "admin", "ids": ["MDG.3.4"]}}},
  "metadata": {"aoi": {"provider": "gadm", "version": "4.1"}},  // the server's echo
  "agent_values": [[658496.56]],    // per trial, aligned with `trials`: the agent's
                                    // own pulled figure for each value; null where
                                    // its pull lacked one
  "unresolved": "column 'x' not in the response"  // only when the selector missed
}

// on the run, present when any entry has one
"ground_truth": {
  "base_url": "https://analytics.globalnaturewatch.org",
  "cases": 1,
  "prefetch_seconds": 3.4,          // summed across sessions on a resumed run
  "tolerance": 0.02                 // relative tolerance the run graded with
}
```

`validate_run` in `src/goldset/ledger.py` requires `run_id`, `started`,
`environment`, `build`, `ff`, `harness`, `judge_model`, `num_trials`,
`caseset_version` and `results`. Runs before 2026-08-04 lack `workers`,
`trial_timeout` and `caseset`; to find which store such a run loaded, match
its `caseset_version` against the manifests' git history.

Optional fields, written only when they apply:

| Field | Level | Meaning |
|---|---|---|
| `methodology_note` | run | The `--note` text: check semantics changed since the previous run, so movement on those checks is not an agent change. |
| `resumed` | run | `true` when the run was finished with `gold run --resume`; its timing mixes two sessions. |
| `error` | entry | The agent call failed or timed out, or the harness hit an error. The row verdict is `error`, never `fail`. |
| `judge_errors` | entry | Checks whose judge call failed. They stay `null` and the row verdict is `error`. |
| `info` | entry | `{"slow": true, "threshold_s": 180.0}` when the case took longer than `--slow-threshold`. Never scored. |
| `ground_truth` | run | Present when any case carried `expected.ground_truth`: the analytics host, the number of cases fetched, the fetch time and the grading tolerance. |
| `ground_truth` | entry | What was fetched for a ground-truth case and how (shape above). See "Ground truth is recorded, not trusted" below. |
| `turns_detail` | entry | Multi-turn cases only: each turn's query, reasons, latency and trace URL. Their checks sit in `checks` as `t<N>.<check>`. |
| `stale_case`, `drift`, `joined_by` | entry | Written only by the retired gnw-evals import tool, present on a couple of the oldest committed runs; see "Stale means stale" below. |

## Rules

- **Keying.** Results reference cases by `uid`. If a case was edited since
  the run, the uid mismatch makes that visible instead of silently
  attributing old scores to new content. Runs also record the whole-set
  `caseset_version`. Diffs cover only the uids both runs share, so a
  growing case set never shows up as regressions or recoveries (see
  [Comparing two runs](#comparing-two-runs)).
- <a id="stale-means-stale"></a>**Stale means stale.** Only the legacy
  importer, `tools/ingest_run.py`, writes `stale_case: true`. A row that
  carries a uid joins on that uid alone: if the store no longer holds it,
  the row is stale and is never re-matched through a weaker join, however
  well its query still matches, because that would attach old scores to
  edited case content. A row with no uid (legacy sheet runs) may join on
  `id` plus the exact query, with a warning (`joined_by: "test_id"`), and is
  stale if the case's expected values have changed since (`drift` lists
  them). Stale rows stay in the file but are left out of diffs and
  flakiness. `gold run` always writes current uids. Separately,
  `tools/report_run.py` shows `stale_case` as the status of a failing row
  whose uid the current store no longer holds, which means the case was
  edited after the run.
- **Run files are immutable.** `write_run` refuses to overwrite an existing
  run file with different content; byte-identical re-ingest (idempotence) is
  allowed. Re-ingesting after a tooling fix means deleting the file first,
  visibly, in a reviewable commit.
- **In-flight state is a sidecar, never the run file.** While a run
  executes, completed entries stream to `results/runs/<run_id>.partial.jsonl`
  (gitignored, fsynced per case). The immutable run JSON is still written
  once, at the end, and the partial deleted. A killed run is finished with
  `gold run --resume <run_id>`; a record completed that way carries
  `resumed: true` (its timing mixes two sessions; everything else is
  identical to an unbroken run).
- **Checks are tri-state.** `1.0` pass, `0.0` fail, `null` not evaluated.
  A case's expected values imply checks that must evaluate
  (`buckets.implied_checks_for_case`). `tools/report_run.py` prints the
  reconciliation line: how many implied checks were actually evaluated,
  with each miss listed, so a check that silently stopped running shows up.
- **Multi-trial runs** (`num_trials` above 1) still store one entry per
  case. Its `checks` map holds each check's majority verdict: pass only if
  more than half of the trials that evaluated it passed (ties fail), `null`
  if no trial evaluated it. `trials` lists every trial as
  `{"checks": {...}, "latency_s": ...}`. `error` and `judge_errors` collect
  the errors of every trial; `reasons`, `actuals`, `latency_s`, `trace_url`
  and `turns_detail` come from the last trial.
- **Ground truth is recorded, not trusted.** A case carrying
  `expected.ground_truth` is graded against values fetched from the
  production analytics API before any trial, and its entry records what was
  fetched and how. The API exposes no data-version field, so `digest` (a hash
  of the values the selector picked, not of the whole response) is the only
  sign that data moved: a digest that differs between two runs means that
  case's data changed. It is omitted on an unresolved selector, where it
  would be the same constant for every such case and prove nothing.
  `tools/diff_runs.py` reads it to file data bumps (see
  [Comparing two runs](#comparing-two-runs)), and reads `agent_values` to
  flag a bump that may hide a real agent break.
- **No fabricated or backfilled runs.** A run file is written by
  `gold run` (or, for legacy runs, `tools/ingest_run.py`) from real harness
  output, never by hand.

## Comparing two runs

`tools/diff_runs.py <older> <newer>` compares two runs check by check, on
every case both runs scored, and reports regressions (pass to fail),
recoveries (fail to pass), data bumps (below) and coverage changes (a check
that started or stopped being evaluated). The count means something only when the two runs
are comparable. Check these before you diff, and before you trust a count
someone else produced:

1. **Same `ff`.** Each profile gives the agent different tools, so a diff
   across profiles measures the profile, not the build. The run_id ends
   with the ff: `20260831T163347Z_prod` (default profile) cannot be diffed
   against `20260831T155003Z_prod_experimental`.
2. **Same trial count, and 3 trials for anything that yields a regression
   count**: a release gate, a baseline, a before-and-after comparison. Read
   `num_trials` in each file. A 1-trial run is a smoke run and is never
   diffed (see [Running the set](../README.md#running-the-set)).
3. **Same environment** (`staging`, `prod` or `local`, also in the run_id).
   Environments usually run different agent builds, so a diff across them
   measures the environment.

`caseset_version` may differ. The diff covers only the uids present in both
runs (stale rows excluded), so added, removed or edited cases show up as
"only in A" or "only in B", never as regressions or recoveries. Report the
number of shared cases with the result, because a small overlap makes a
weak verdict. Pass `--strict` to refuse any pair whose `caseset_version`
differs.

To pick a baseline, `tools/find_baseline.py <new run>` prints the newest
run in `results/runs/` that meets all three conditions and also loaded the
same store (`caseset`), and exits non-zero with the reason when none does.
The CI release gate uses it. Runs from before 2026-08-04 record no
`caseset`, so they never match.

**Why 3 trials.** Two trials of the same run (same build, same cases,
nothing changed) differ by 18 to 29 spurious regressions. That is more than
the 15 real regressions measured between two different builds, so a
1-trial diff cannot tell a clean release from a broken one, and a 1-trial
run diffed against a 3-trial baseline is worse. Comparing the three trials
stored in `20260831T163347Z_prod` pairwise gives the same band.

**Info-only checks never gate.** Checks in `buckets.INFO_ONLY` (see
[Info-only checks](../src/goldset/evaluators/README.md#info-only-checks)),
including multi-turn ones under a `t<N>.` prefix, appear in the diff, but
`--fail-on-regression` and `--fail-on-coverage-loss` ignore them. The
headline splits regressions and lost checks into gating and info-only
counts, and the JSON report's `gating_regressions` and
`gating_coverage_lost` are what the two flags read. If the newer run carries a `methodology_note`, movement on the
checks it names comes from a harness change, not from the agent.

**Data bumps are not regressions.** A ground-truth case is graded against
values fetched when the run starts, so a data release can flip it with no
agent change. When a ground-truth check flips and the case's `digest` moved,
the diff lists it as a data bump with its cause: `data` (same request,
different numbers), `request` (GOLD's own request changed, so a harness
change) or `fixed_dataset` (a dataset declared never to change has changed).
Bumps are never counted as regressions or recoveries and never gate. A
`ground_truth_match` bump whose agent figure matches neither run's values,
or that has no figure, is flagged `possible_hidden_regression`: review it
before trusting the regression count, because a break that lands in the
same run as a data change would otherwise never be counted.

## Composing a current picture across runs

A scoped re-run is often all that's needed: when only a handful of rows changed,
or when one capability was unreachable (a missing `ff`, a service outage). The
temptation is then to write those fresher scores into the earlier run file so
there is a single number to quote. **Don't.** `write_run` refuses it and the rules
above forbid it, but the deeper reason is that a run record also describes *how*
its rows were produced (`ff`, `workers`, `build`, `harness`, `caseset_version`).
Splice in rows produced under different conditions and that metadata becomes
false, which misleads the next person to diff the file.

Compose in the **analysis** instead:

```bash
uv run python tools/compose_runs.py results/runs/<primary>.json \
    results/runs/<supplementary>.json
```

It resolves every active case to its freshest measurement **at the case's current
uid** (supplements win over the primary, later supplements over earlier), prints
per-row provenance, names any row nothing has measured, warns when the sources
disagree on `ff`, and writes nothing to `results/runs/`. Both runs stay in the
ledger as honest, independently reproducible records; only the summary is joined.

## Ledger resets

- **2026-08-04: v2 baseline reset.** Runs scored against intermediate v2
  curation states (2026-08-02 and 2026-08-03) and their reports were
  deleted, so the v2 record starts at the first official v2 run. They remain
  in git history. The v1 runs from 2026-07-31 and 2026-08-01, and the
  recommendations and campaign docs from that period, were kept.
