# CLAUDE.md

This file guides Claude Code when working inside `evals/gold/` — the GOLD capability regression suite, nested inside project-zeno as its own standalone project (own `pyproject.toml`, `uv.lock`, virtual environment). Terms are defined in the [README glossary](README.md#glossary). Run every command below from this directory.

## What this is

GOLD is the capability regression suite for the Project Zeno agent: cases, harness and results ledger together. It answers one question per release: *did an agent change break a capability that used to work?* The headline is a **regression count**, never a mean score, and determinism outranks realism in every design call.

It lives inside project-zeno (not a separate repo) so a change to the agent and the case fix it requires can land in the same PR, and so `--env local` runs against `make api` from this same checkout with no separate clone to keep in sync.

Before proposing changes, read `README.md`, `cases/README.md` and `results/README.md`. Where a rule below rests on a design decision, its reason is given with it.

## Commands

```bash
uv sync                                                        # install (Python 3.11+), in this directory
uv run pytest -q                                               # full suite, no network
uv run pytest tests/test_canonical.py -q                       # one file
uv run pytest tests/test_store.py::test_write_read_round_trip  # one test
uv run ruff check src tools tests                              # lint, as CI runs it

# Runs. Tokens: STAGING_API_TOKEN / PROD_API_TOKEN, else API_TOKEN;
# .env (in this directory) is loaded automatically (README "Setup").
uv run gold run --env staging --build "<label>"              # smoke: 1 trial, 10 workers
uv run gold run --env staging --trials 3 --build "<label>"   # official / release gate
uv run gold run --env local                                  # against `make api` run from the project-zeno root
uv run gold run --resume <run_id>                            # finish a killed run
uv run gold run --dry-run                                    # list selected cases, no API calls

# After any case edit: all three, committed with the edit
uv run python tools/check.py --fix
uv run python tools/coverage_doc.py
uv run python tools/audit_cases.py --strict

uv run python tools/sync_zeno_catalog.py   # refresh the dataset catalogue snapshot
```

## Rules for runs

Procedures and reasons: README ["Running the set"](README.md#running-the-set) and ["After a run"](README.md#after-a-run).

- **Profile.** Run the default profile (no `--ff`) unless the cases under test need a feature still behind `experimental`. Never diff or trend across differing `ff`; the run_id suffix shows it (`_prod` versus `_prod_experimental`).
- **Two tiers.** A smoke run (1 trial, the CLI default) is never committed, diffed or used as a baseline. Anything that produces a regression count or becomes a baseline uses `--trials 3`.
- **Local runs are always smoke.** `--env local` targets a locally-booted agent, which doesn't match staging or prod — never commit or diff a local run, whatever the trial count.
- **Ephemeral runs are CI-only.** `--env ephemeral --api-base-url <url>` is how `.github/workflows/gold-ephemeral.yaml` runs the set against a per-commit deployment. Never commit those runs or diff them against staging or prod (README ["Running the set"](README.md#running-the-set)).
- **Comparable runs only.** Both sides of a diff need the same `ff`, the same trial count and the same environment ([Comparing two runs](results/README.md#comparing-two-runs)). If no comparable run exists, say so rather than diffing against something else.
- **Methodology note.** If check semantics changed since the previous run, pass `--note "<what changed>"` when starting `gold run`, so diffs are not read as agent changes.
- **Ground truth.** Cases with `expected.ground_truth` fetch their expected figures from the production analytics API, whatever `--env`, once per run before the first trial. A failed fetch aborts the run before any agent call, so nothing is written. Because every run fetches afresh, two runs can differ with no agent change; `diff_runs.py` files those flips as data bumps, never regressions ([Run-time ground truth](cases/README.md#run-time-ground-truth-ground_truth)).
- **Timeouts.** A block of `ReadTimeout`s late in a run usually means too many workers (runs record `workers` and `trial_timeout` so this can be traced). Lower `--workers` before blaming the agent.
- **Finish official runs.** An official run is not done until the four steps in README "After a run" are complete. Show the user what will be committed before committing.
- **The ledger is written by the harness only.** Never hand-write, edit, backfill or splice a run file. To combine a full run with a scoped re-run, use `tools/compose_runs.py` ([results/README.md](results/README.md)).

## Rules for cases

**COVERAGE.md must move with the case set.** Any change to a case file (query, expected values, status, group, notes, or a new or deleted case) is incomplete until `tools/check.py --fix` and `tools/coverage_doc.py` have run and their output is committed with the edit; run `tools/audit_cases.py --strict` as well. CI fails the PR on a stale uid or manifest, a stale COVERAGE.md (a changed `Last updated` date alone does not count) or an audit violation. Procedure: README ["Changing cases"](README.md#changing-cases).

- Status changes follow [Status lifecycle](cases/README.md#status-lifecycle). In particular, `done` needs a passing 3-trial run at the case's current uid, cited by run_id in `notes.status_reason`, and parking needs a dated `status_reason`.
- If a case breaks because the agent change in your PR is an intentional, correct new behaviour (not a regression), fix the case's query or expected values in the same PR and say so in the PR description — that's the whole point of this living here. If you're not sure which it is, that's a question for review, not something to resolve by loosening the expectation.

## The identity system

**WARNING**: critical for the ledger. Do not break it. Every result in `results/runs/` is keyed on a case's uid, so the uid is the only link between a score and the exact case content it was measured against. If the hash changes for content that did not change, every committed run stops matching its cases and the regression history is lost. If the hash misses a change that did happen, old scores are silently attributed to the edited case, and diffs compare two different tests as if they were one. `src/goldset/canonical.py` defines the hashing; the README glossary defines [uid](README.md#uid) and [caseset_version](README.md#caseset-version).

- **uid** = `sha256(canonical_json(query + non-empty expected values))[:16]`. Changing the query or any `expected` value mints a new uid: that is the versioning mechanism, not an error. `status`, `group`, `notes`, key order, leading and trailing whitespace, and line endings never affect it, so triage never mints a version.
- **Multi-turn uids** hash every turn's query and expected values in order, so reordering turns mints a new uid, and every turn's `deltas` are hashed too.
- **The hash covers every expected field, scored or not** (for example `dataset_name`, which no check reads). An unscored field is still part of what the case asserts, and a check may start reading it later; if the hash skipped it, an edit to it would change the case without a new uid. Do not narrow the hash to scored fields, and do not move expectations into `notes` to avoid uid churn.
- **caseset_version** (in `cases/v2/MANIFEST.json`) hashes the sorted uids. Results key on uid; diffs run over the uids two runs share.
- **`id`** (such as `1-030`) is the stable lineage handle across versions.
- `tests/test_schema.py` validates every case file against `schema/case.schema.json`, so a malformed case fails the suite, not a run.

## Dataset coverage against project-zeno

COVERAGE.md's "Dataset coverage" section measures the case set against the agent's dataset catalogue (`../../src/agent/datasets/catalog/*.yml`), read from the committed snapshot `cases/zeno_catalog.json` so that CI needs no network. When the catalogue changes, run `tools/sync_zeno_catalog.py`, then `tools/coverage_doc.py`, and commit both together. The sync reads `origin/main` of this same repository with `git show` and never touches the working tree (`--zeno` and `--ref` override the defaults) — this keeps the snapshot pinned to a reviewed, committed ref even though the catalogue files sit in the same checkout, so a mid-PR edit to a dataset can't silently change what coverage is measured against.

The snapshot is also the ground-truth request table. It carries each dataset's `analytics_api_endpoint`, `content_date`, `content_date_fixed`, `start_date` and `end_date`, and `src/goldset/groundtruth/catalog.py` builds every analytics request from them, so a dataset whose window grows upstream cannot leave ground truth computed over the old one. Payload shape, the 4/8/10 `intersections` split and the AOI type map have no YAML form in project-zeno (they are code in its `_build_payload` and `_get_aoi_type`), so `catalog.py` hardcodes them and they change only with a reviewed upstream change. A dataset missing from the snapshot has no request, and a case that needs it fails the run loudly.

## Architecture

- `src/goldset/`: the library.
  - `canonical.py`: uid and caseset_version hashing.
  - `store.py`: the `Case` dataclass, case YAML read and write, manifests. Unknown top-level keys are rejected on read.
  - `templates.py`: `{token}` dates in queries, resolved when a run starts (the uid hashes the token).
  - `adapter.py`, `eval_types.py`: turn a case's expectations into the harness's typed inputs, and define its result type.
  - `runner/`: API calls (`api.py`), multi-turn threads (`multiturn.py`), raw artefact capture (`artifacts.py`).
  - `evaluators/` and `registry.py`: the checks, and the order the runner calls them in.
  - `models.py`: the LLM judge client; `judge_config.py`: the judge backend (`--judge-backend`) and the model name recorded on runs.
  - `groundtruth/`: run-time ground truth: selector parsing, analytics requests built from the catalogue snapshot, and the fetch before the first trial.
  - `buckets.py`: the bucket map, the info-only set, row verdicts, and the reconciliation of implied with evaluated checks.
  - `ledger.py`: run records, run_ids, majority verdicts and partial files.
  - `cli.py`: the `gold` command.
- `tools/`: thin CLIs over `src/goldset` (they add `src/` to `sys.path`); see `tools/README.md`.
- `cases/v2/<group>/<id>.yaml`: one case per file, so review, blame and revert work per case. `expected:` holds the hashed expectations (keys without the `expected_` prefix); `notes:` holds unhashed annotations.
- `results/`: the committed ledger; contract in `results/README.md`. Checks are tri-state `1.0`/`0.0`/`null`.
- `schema/case.schema.json`: the case contract. `templates/`: the HTML report templates.
- The case store is the source of truth; nothing here writes back to a spreadsheet or a separate harness.

## Working agreements

- Numbers in code; structure and semantics to the judge. No LLM judge is ever asked to do arithmetic.
- Every check's documentation decides whether a missing input scores `null` (not evaluated) or `0.0` (fail), and says why.
- A new judged check starts info-only and gates only once it shows a standard deviation of at most 0.10 over a 3-trial run (`tools/flakiness.py`). The three judged checks inherited from gnw-evals (`agent_answer`, `expected_text_match`, `clarification_requested`) already gated and still do.
- Judge structured outputs put the reasoning field before the score field.
