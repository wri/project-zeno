# GOLD

GOLD is the capability regression suite for Project Zeno, the LLM agent behind Global
Nature Watch (GNW) Horizon. This directory holds the GOLD cases, the harness that
runs them against the agent, and the committed ledger of results, as a standalone
project (its own `pyproject.toml`, `uv.lock` and virtual environment) nested inside
the agent repo it tests.

GOLD answers one question before each release: **did an agent change break a
capability that used to work?** So coverage across capabilities is the design goal
and a nearly deterministic case beats a realistic one.

Every case is a versioned file and every result is pinned to the exact case content it was scored against — editing a case's query or any expected value mints a new identity for it, so an old score is never silently read as a score for new content. Project terms are defined in the [Glossary](#glossary).

## How it works

A **case** is a YAML file (under `cases/v2`) holding a user query (or a scripted
conversation) and the values a correct answer must contain: the place ids, the
dataset, the date range, a figure. `uv run gold run` sends each query to the agent's
API, waits for the answer, then fetches the agent's final state for that
conversation. **Evaluators** compare that state with the case's expected values and
produce **checks**, with a score of pass, fail or not evaluated. Each check relates
to one or two of five **buckets** (retrieval, analysis, explanation, output, scope),
so a failure points at the stage that broke. The run is written to `results/runs/` as
a JSON record, which can be committed. Before a release, `tools/diff_runs.py`
compares the candidate build's run with a baseline run and counts **regressions**:
checks that passed before and fail now.

Results are keyed by case content, not by case name. Every case has a [uid](#uid), a hash of its query and expected values, so editing a case gives it a new uid and an old score is never read as a score for the new content. The store of cases (`cases/v2`) has a [caseset_version](#caseset-version), a hash of all its uids.

## Running the set

`gold run` sends every case in `cases/v2` whose status is not `not doing` to the agent, scores it, and writes one run record to `results/runs/<run_id>.json`, plus raw agent state under `results/artifacts/<run_id>/` (gitignored).

The default value for the arguments are: workers (10, max 20 allowed), trials (1),
env (staging). The most reliable run uses at least 3 trials per case.
s
```bash
uv run gold run --env staging --workers 5                    # smoke run: 1 trial
uv run gold run --env staging --trials 3                     # official run against staging
uv run gold run --env staging --id 1-030 --verbose           # one case (repeat --id for more)
uv run gold run --env local                                  # Run against local 'make api'
uv run gold run --dry-run                                    # list the selected cases; no API calls
uv run gold run --help                                       # every flag
```

## Glossary

Definitions only: counts are in [cases/v2/COVERAGE.md](cases/v2/COVERAGE.md), and rules are in the sections below and in [CLAUDE.md](CLAUDE.md).

### The product

- **Project Zeno, the agent**: the LLM agent behind GNW, built in [wri/project-zeno](https://github.com/wri/project-zeno). The harness asks it a question with `POST /api/chat`, then reads its final state with `GET /api/threads/{id}/state`; checks score that state.
- **GOLD**: this suite, a capability regression check run before each release (also called the capability smoke-test set
- **harness**: the code here that sends each case to the agent, fetches the final state and scores it (`src/goldset/runner/`, run with `gold run`).
- **environment**: the agent deployment a run targets: `staging`, `prod`, `local` (`http://localhost:8000`) or `ephemeral` (a per-commit CI deployment, needs `--api-base-url`). Recorded on the run and in its run_id.
- <a id="profile"></a>**ff, tool profile**: `ff` (feature flag) is a field in the chat request that picks the agent's tool profile. Leaving it out gives the default profile; `experimental` adds features not yet released to the default. A run records its `ff`, and its run_id ends with it. See [Running the set](#running-the-set).
- **AOI (area of interest)**: the place a question is about, as the agent resolved it: one or more ids from a boundary source (`aoi_source`), which is `gadm`, `kba`, `wdpa` or `landmark`.
- **GADM**: the Database of Global Administrative Areas: country, state and district boundaries. Ids look like `BRA.25_1`: a country code, admin-level numbers, then a `_N` suffix that `aoi_id_match` ignores.
- **KBA, WDPA, Landmark**: the other AOI sources: Key Biodiversity Areas, the World Database on Protected Areas, and LandMark (indigenous and community lands).
- **dataset, catalogue**: the agent's datasets are numbered and defined in project-zeno's dataset catalogue (`src/agent/datasets/catalog/*.yml`). A case's `dataset_id` names the dataset it expects. A retired dataset id, such as 0 (DIST-ALERT), is never reused.
- **nudge**: the agent's structured follow-up offer, held in the `nudge` state field as `{type, options, data?}`. A `dataset_choice` nudge offers datasets (scope `suggest`); other types, such as `aoi_choice`, ask the user to pick or clarify (scope `clarify`). It replaced the older `suggested_datasets` field, which the agent no longer writes.
- **send_nudge**: the agent tool that writes a nudge with fixed arguments, the most deterministic kind of nudge.
- **thread**: one conversation with the agent. Each trial runs in a fresh thread; a multi-turn case sends all its turns to one thread.

### Cases and stores

- **case**: one test, stored as one YAML file at `cases/<store>/<group>/<id>.yaml`: a query (or turns), the expected values it is graded on, a status, a group and free-form notes.
- **id**: a case's stable, human-readable name, such as `1-030` (single-turn) or `mt-005` (multi-turn). It survives edits, so it links every version of one test.
- <a id="uid"></a>**uid**: a 16-character hash (truncated SHA-256) of a case's query and every non-empty expected value; for a multi-turn case, of every turn in order (in v2, including each turn's `deltas`). Editing the query or any expected value gives a new uid; status, group and notes never do. Results are keyed by uid. The exact rules are in [CLAUDE.md](CLAUDE.md#the-identity-system).
- <a id="caseset-version"></a>**caseset_version**: a 16-character hash of the sorted uids of every case in a store, kept in the store's `MANIFEST.json`. It changes when a case is added, removed or given a new uid. Two runs with the same caseset_version scored the same case content; runs with different ones can still be compared over the cases they share ([Comparing two runs](results/README.md#comparing-two-runs)).
- **store**: a directory of case files plus its generated `MANIFEST.json`. `cases/v2` is the working set: all edits go there and every tool uses it by default.
- **MANIFEST.json**: a per-store file written by `tools/check.py --fix`: the caseset_version plus an id-to-uid index.
- **expected, notes**: `expected` holds the values a case is graded on; each non-empty key switches on one or more checks and is part of the uid. `notes` holds annotations, such as `status_reason` and `env_gated`, that are never hashed or scored.
- **group**: the capability a case tests (`direct`, `temporal`, `dashboard` and so on); also the name of its directory.
- **status**: where a case is in its lifecycle: `ready`, `todo`, `done` or `not doing`. Every status except `not doing` runs by default. See [Status lifecycle](cases/README.md#status-lifecycle).
- **park, unpark**: set a case to `not doing` with a dated reason in `notes.status_reason`, or bring it back. An unparked case must show again that the reason it was parked no longer holds.
- **scope**: the kind of work a case expects: `analyse` (pull data and answer), `suggest` (offer datasets), `clarify` (ask the user to choose) or `refuse` (decline). The harness classifies the agent's final state into one of these; `refuse` matches a state with no data pull, no suggestion and no nudge.
- **`;` in expected values**: in `dataset_id`, `scope`, `nudge_type` and `chart_type`, `a;b` means either value is acceptable. In `aoi_ids` it means all of them (the two sets must match). Other fields have their own rules, given with each check in the [evaluators README](src/goldset/evaluators/README.md#index).
- **multi-turn case, deltas**: a case with `turns:` instead of one query and expected block; all turns share one thread. A turn's `deltas` say which state fields must have `changed`, stayed the same (`retain`) or become empty (`absent`) since the previous turn, scored as the `state_delta` check.
- <a id="ground-truth"></a>**ground truth**: an `expected.ground_truth` selector, such as `sum(area_ha) WHERE year=2019`, that names a figure instead of pinning its value. The harness fetches the value from the analytics API when the run starts, so the case survives data releases with its uid. See [Run-time ground truth](cases/README.md#run-time-ground-truth-ground_truth).
- **query template**: a token such as `{current_year}` in a query, replaced with a concrete date when the run starts. The uid hashes the token, not the date, so the case keeps its identity as time passes.
- **env_gated**: a note on a case whose capability is missing in some environment or profile, so its zeros are not read as regressions. Only people read it; no code does.
- **sentinel**: a deliberately loosely worded case, kept so that a drift towards over-nudging is still caught.
- **depth rule**: a case's expected values must imply at least two checks in at least two buckets, so a pass always measured something. CI enforces it ([The audit gate](cases/README.md#the-audit-gate)).
- **COVERAGE.md**: `cases/v2/COVERAGE.md`, a generated report of what v2 covers: groups, buckets, expected fields, datasets and parked cases. Never edit it by hand; CI fails if it is out of date.
- **catalogue snapshot**: `cases/zeno_catalog.json`, a committed copy of the agent's dataset catalogue, so COVERAGE.md can be generated without network access. It also holds the analytics endpoint and date window that ground-truth requests are built from.

### Runs and results

- **run**: one execution of the selected cases against one environment, written as one run record.
- <a id="trial"></a>**trial**: one execution of one case within a run, in a fresh thread. `--trials 3` runs each case three times; the run stores each check's majority verdict and every trial's scores.
- **majority verdict**: a check's result across trials: pass if more than half of the trials that evaluated it passed, otherwise fail (a tie fails); not evaluated if no trial evaluated it.
- <a id="smoke-run"></a>**smoke run, official run**: the two run tiers. A smoke run (1 trial, the default) is for quick iteration and is never committed, diffed or used as a baseline. An official run (3 trials) is anything that produces a regression count or becomes a baseline. See [Running the set](#running-the-set).
- **build label**: free text passed with `--build` naming the agent build under test (default `unknown`). The harness records it as given; it does not ask the API.
- **run record, ledger**: a run record is the JSON file one run writes to `results/runs/`, immutable once written. The ledger is the committed set of run records. Nothing in it is ever written or edited by hand. Contract: [results/README.md](results/README.md).
- **run_id**: a run record's name, `<YYYYMMDD>T<HHMMSS>Z_<env>[_<ff>]` in UTC, for example `20260831T163347Z_prod`. The suffix shows the environment and `ff` at a glance.
- **partial file**: `results/runs/<run_id>.partial.jsonl` (gitignored), where a run appends each finished case so that a killed run can be resumed.
- **artefacts**: raw agent state for each case and trial, gzipped under `results/artifacts/<run_id>/` (gitignored). They keep evidence a run record does not. `uv run gold prune-artifacts` deletes all but the newest runs' artefacts.
- **methodology note**: text passed with `--note` and stored as `methodology_note` on the run, recording that check semantics changed since the previous run.
- **regression, recovery**: between two runs, for a case uid present in both: a check that went from pass to fail (regression) or from fail to pass (recovery). Counted per check, not per case. Info-only checks never count towards the gate.
- <a id="data-bump"></a>**data bump**: a ground-truth check that flipped between two runs while the digest of its fetched values moved, so the data changed under the case. `diff_runs.py` lists bumps but never counts them as regressions or recoveries, and they never gate. A bump that the agent's own recorded figure does not explain is flagged as a possible hidden regression.
- **coverage loss, coverage gain**: a check that went from evaluated to not evaluated (loss) or the reverse (gain) between two runs. A check that stopped running has not passed.
- **comparable runs**: two runs whose diff means something: same `ff`, same trial count (3) and same environment. The caseset_version may differ, because a diff only covers uids present in both runs. See [Comparing two runs](results/README.md#comparing-two-runs).
- **baseline**: the official run a new run is diffed against: the most recent committed official run that is comparable with it.
- **release gate**: the check before a release: `tools/diff_runs.py --fail-on-regression` between the baseline and an official run of the candidate build. See [The release gate](#the-release-gate).
- **stale_case, stale expectation**: `stale_case` marks a result whose uid the current store no longer holds ([results/README.md](results/README.md)). A stale expectation is something else: an expected value that is out of date, so the case fails although the agent is right.
- **flaky check**: a check whose trials disagree within one run. `tools/flakiness.py` reports each check's mean, standard deviation and number of flips across trials.
- **compose**: build a current picture from a full run plus scoped re-runs with `tools/compose_runs.py`. It works in the analysis only and never writes to the ledger.
- **recommendations doc**: `results/recommendations/<run_id>.md`, written after each official run. See [After a run](#after-a-run).
- **probation, re-admission**: a trial period before something is trusted again. An info-only check must meet its stated condition before it gates again; an unparked case must show that the reason it was parked no longer holds.

### Scoring

- **check**: one named score on a case, such as `aoi_id_match`. Every check is tri-state.
- **evaluator**: a function of the agent's final state and the case's expected values that returns one or more checks. Evaluators are registered in `src/goldset/registry.py`.
- **deterministic, judged**: how a check decides: in code, or by asking the LLM judge. Some checks combine the two (for example, the judge picks the figure out of the prose and code compares it); the evaluators README says which.
- **judge**: the LLM (`claude-haiku-4-5` unless `--judge-backend` picks another) that scores judged checks. It is never asked to do arithmetic; numbers are compared in code.
- **tri-state**: every check scores `1.0` (pass), `0.0` (fail) or `null` (not evaluated). Each check's documentation says when a missing input scores `null` and when it scores `0.0`.
- **implied check, reconciliation line**: implied checks are those a case's expected values guarantee will be evaluated. A report's reconciliation line compares the implied count with the evaluated count, so a check that silently did not run shows up.
- <a id="bucket"></a>**bucket**: one of five pipeline stages a check speaks for: retrieval, analysis, explanation, output and scope (see [How scoring reads](#how-scoring-reads)). A **dedicated** check belongs to one bucket; a **shared** check belongs to two, because its failure cannot be pinned on one.
- <a id="info-only"></a>**gating, info-only**: a gating check can turn a row's verdict to fail. An info-only check is recorded and reported but never affects a row verdict or the release gate; new judged checks start info-only. The list is `INFO_ONLY` in `src/goldset/buckets.py`, explained in [Info-only checks](src/goldset/evaluators/README.md#info-only-checks).
- <a id="row"></a>**row, row verdict**: a row is one case's result in a run (the word dates from the sheet). Its verdict is `pass`, `fail` (a gating check scored `0.0`), `error` (an API or judge failure, never counted as a fail) or `uncovered` (no gating check was evaluated, never counted as a pass).
- **judge error**: a judge call that failed. The check stays `null`, its name is recorded in `judge_errors`, and the row verdict becomes `error`.
- **gate**: used for several things, so say which: the CI checks on every PR; the audit gate (`audit_cases.py --strict`); the release gate (`diff_runs.py --fail-on-regression`); a check being gating; the flakiness limits.

## Setup

You need Python 3.11 or later and [uv](https://docs.astral.sh/uv/).

```bash
uv sync                               # install, including the dev tools
uv run python -m pytest -q            # the full suite; needs no network or secrets
uv run ruff check src tools tests     # lint, as CI runs it
```

Live runs need two secrets, set in your shell or in a `.env` file in this directory (`evals/gold/.env`, gitignored, separate from project-zeno's own root `.env`; `gold run` loads it before checking for a token):

- **An API token for the target environment**: `STAGING_API_TOKEN` for `--env staging`, `PROD_API_TOKEN` for `--env prod`. If that variable is not set, the CLI falls back to `API_TOKEN`, which is also the only one `--env local` reads. So a stale environment-specific token in `.env` wins over a fresh `API_TOKEN`.
- **Judge credentials**: `ANTHROPIC_API_KEY` for the default judge. With `--judge-backend openrouter-jev-decisions` the judge is TypeSafe JEV through OpenRouter Decisions, which needs `OPENROUTER_API_KEY` instead.

Cases with `expected.ground_truth` also call the production analytics API. They use `ANALYTICS_API_TOKEN` when it is set, and the API token otherwise.

**Choose the tier before you start.**

- A **smoke run** (1 trial, the default) answers a quick question in minutes, such as "did my prompt rewrite stop the nudge?". It is never committed, never diffed and never used as a baseline.
- An **official run** (`--trials 3`) is anything that produces a regression count or becomes a baseline. It needs three trials because the agent is not deterministic: two single trials of the same build differ by more spurious regressions than a real build change produced ([Comparing two runs](results/README.md#comparing-two-runs) has the evidence). Give it a meaningful `--build` label, such as the agent build string or a purpose like `post-fix-validation`, not the default `unknown`.

**Use the default tool profile.** Leave out `--ff` unless the cases under test need a feature still behind the `experimental` profile, such as the LGMS dataset (id 12). The run records its `ff`, and the run_id ends with it (`20260831T163347Z_prod` versus `20260831T155003Z_prod_experimental`). Never diff or trend two runs with different `ff`: the profiles offer different tools, so the diff would measure the profile, not the release. Cases that need `experimental` are parked (`not doing`) while official runs use the default profile; each one's `status_reason` says when to bring it back. Until late August 2026, dashboards and satellite imagery existed only behind `experimental`, so every run before 2026-08-31 used `ff=experimental`; do not compare those runs with later default-profile runs.

**Record semantic changes.** If check semantics changed since the previous run, pass `--note "<what changed>"`. It is stored on the run, so later diffs are not read as agent changes.

**Local runs.** `--env local` targets `http://localhost:8000` — run `make api` from the project-zeno root above this directory — and reads only `API_TOKEN`. Local runs are smoke runs: a local stack does not match staging or prod, so never commit or diff them, and local run records are gitignored rather than added to the ledger.

**Ephemeral runs (CI).** `.github/workflows/gold-ephemeral.yaml` runs the whole set (3 trials) against a fresh ephemeral deployment of each push to main, and of each PR when it becomes ready for review; marking a PR ready again re-runs it. To run it by hand on the head of any branch: `gh workflow run gold-ephemeral.yaml --ref <branch>`, optionally with `-f trials=1`, `-f ids="1-030 1-136"` or `-f keep_env=true`; it comments on the branch's open PR if there is one. It deploys the commit with `deploy-ephemeral.yaml`, runs `gold run --env ephemeral --api-base-url <deployment URL>`, posts a summary to the job page and the PR, and then destroys the deployment. `--env ephemeral` needs `--api-base-url` and reads only `API_TOKEN`. The summary's headline is the pass rate over all cases (errored and uncovered rows count against it), flagged red below 90%; it never fails the workflow. Ephemeral runs are their own environment, so like local runs they are never committed or diffed against staging or prod. The run record and HTML report are uploaded as workflow artifacts.

**Killed runs.** A run appends each finished case to `results/runs/<run_id>.partial.jsonl` (gitignored), so a killed run loses only the cases that were in progress. `uv run gold run --resume <run_id>` finishes it: the settings come from that file (every other flag except `--results-dir` is ignored), it refuses if the case set has changed, and the final record carries `resumed: true`.

**Workers and timeouts.** By default 10 cases run at once (the hard cap is 20), and a trial that takes over 900 seconds becomes an error row. Runs record both settings. A block of timeouts late in a run usually means the API is overloaded: lower `--workers` before blaming the agent.

## The release gate

Before a release, diff an official run of the candidate build against the baseline: the most recent committed official run that is comparable with it. If there is none, first make one with the build currently released.

```bash
uv run python tools/diff_runs.py results/runs/<baseline>.json results/runs/<candidate>.json \
  --fail-on-regression --fail-on-coverage-loss
```

`--fail-on-regression` exits 1 on any regression in a gating check; `--fail-on-coverage-loss` also fails when a gating check stopped being evaluated. The count only means something if the two runs are comparable: same `ff`, same trial count (3) and same environment. [Comparing two runs](results/README.md#comparing-two-runs) gives the conditions and the evidence behind them; the `release-gate` skill walks through the verdict. Ground-truth flips caused by a data change are reported as [data bumps](#data-bump), not regressions; review any flagged as a possible hidden regression before trusting the count.

## After a run

An official run is not finished when its JSON lands; it is finished when someone can act on it. Smoke runs skip these steps and are never committed. If check semantics changed since the previous run, the run should already carry `--note` (see [Running the set](#running-the-set)).

1. **Render the reports.**
   ```bash
   uv run python tools/render_html.py results/runs/<run_id>.json   # results/reports/<run_id>.html
   uv run python tools/render_html.py --all        # results/reports/all-runs.html
   uv run python tools/render_inspector.py --all   # results/reports/all-runs_inspector.html
   uv run python tools/render_trends.py            # results/reports/trends.html
   ```
   For a quick read, `uv run python tools/report_run.py results/runs/<run_id>.json` prints a Markdown summary, and `render_inspector.py results/runs/<run_id>.json` builds a matrix of every case against every check for one run. Read the trends page within one `ff` only.
2. **Check flakiness and diff.**
   ```bash
   uv run python tools/flakiness.py results/runs/<run_id>.json --per-case
   uv run python tools/diff_runs.py results/runs/<baseline>.json results/runs/<run_id>.json
   ```
   Diff only against a comparable run ([Comparing two runs](results/README.md#comparing-two-runs)). If none exists, say so in the recommendations doc rather than diffing against something else.
3. **Write `results/recommendations/<run_id>.md`** with four sections:
   - what to report to the agent team, with the failing and flapping rows as evidence;
   - what the run says about the case set (stale expectations, coverage gaps, cases ready to leave probation);
   - what it says about the harness;
   - what to watch on the next run.

   `results/recommendations/20260801T093002Z.md` shows the shape.
4. **Commit** the run JSON and the recommendations doc together, in one commit. Rendered reports are not committed (`results/reports/` is gitignored): they're regenerable from the run JSON, so regenerate them locally whenever you need to look at one.

The `gold-run` skill runs these steps, and the `triage-run` skill helps fill in step 3.

## Changing cases

Read [cases/README.md](cases/README.md) before writing or editing a case: it says what makes a good case and how a case's [status](cases/README.md#status-lifecycle) moves.

After any change to a case file (query, expected values, status, group, notes, or a new or deleted case), run all three of these and commit their output in the same commit as the edit:

```bash
uv run python tools/check.py --fix            # recompute uids and MANIFEST.json (v2 by default)
uv run python tools/coverage_doc.py           # regenerate cases/v2/COVERAGE.md
uv run python tools/audit_cases.py --strict   # depth rule and DON'Ts, as CI runs it
```

CI (`.github/workflows/gold-checks.yml`, on every PR and push to main touching `evals/gold/**`) runs `check.py` (without `--fix`), `coverage_doc.py --check` and `audit_cases.py --strict`, and fails the PR if a uid or manifest is out of date, COVERAGE.md is stale, or the audit finds a violation ([The audit gate](cases/README.md#the-audit-gate)).

Editing the query or any expected value gives the case a new uid, so earlier results no longer match it and a `done` case needs verifying again. That is intended: it keeps every score pinned to the content it measured. Say in the PR which cases changed and why; the PR is the only record of the reason.

When project-zeno adds, removes or changes a dataset, refresh the catalogue snapshot with `uv run python tools/sync_zeno_catalog.py`, then run `coverage_doc.py` and commit both.

## How scoring reads

Every check scores `1.0` (pass), `0.0` (fail) or `null` (not evaluated). Each check's documentation says whether a missing input counts as `null` or `0.0`, because a `null` that should have been a fail hides a regression.

Checks roll up into five buckets, one per stage of the agent's work, so a failure points at the stage that broke:

| Bucket | The question it answers |
|---|---|
| Retrieval | Did the agent understand the question and fetch the right data (place, dataset, dates)? |
| Analysis | Are the numbers right? |
| Explanation | Is the prose faithful to the data? |
| Output | Are charts and dashboards presented correctly? |
| Scope | Did it do the right kind of work: answer with data, suggest datasets, ask the user to choose, or decline? |

Most checks belong to one bucket. A few are shared by two, because their failure cannot be pinned on one, and bucket tables report the two kinds separately. The [evaluators README index](src/goldset/evaluators/README.md#index) maps every check to its bucket.

Info-only checks are recorded and reported but never affect a row verdict or the release gate. They are new or unreliable checks that have not yet earned a vote; [Info-only checks](src/goldset/evaluators/README.md#info-only-checks) lists them with the condition each must meet to gate again.

A run is read through row verdicts and per-bucket tallies, never a flat mean. Each row (one case's result) gets one verdict:

- `pass`: every gating check that was evaluated passed;
- `fail`: at least one gating check scored `0.0`;
- `error`: the API or the judge failed, so the row measured nothing reliable; rerun it before trusting it. It never counts as a fail;
- `uncovered`: no gating check was evaluated, so it never counts as a pass.

**Multi-turn cases** run all their turns in one thread. Per-turn checks are prefixed with the turn number (`t2.aoi_id_match`), and `state_delta` scores the expected changes between turns. A turn that errors ends its conversation, so later turns are not scored against a broken thread.

The tools fail loudly when nothing was measured: `flakiness.py` marks a partial sample INSUFFICIENT DATA instead of calling it stable, `diff_runs.py --fail-on-coverage-loss` fails when checks stop being evaluated, and each report's reconciliation line compares the checks a case should have produced with those actually evaluated.

## Repository layout

```
evals/gold/pyproject.toml, uv.lock   this project's own dependencies and lockfile
cases/v2/                 the working case set: one YAML per case in group folders, plus MANIFEST.json
cases/v2/COVERAGE.md      generated coverage report; never edit by hand
cases/zeno_catalog.json   snapshot of the agent's dataset catalogue, read by coverage_doc.py
schema/case.schema.json   the case file contract; tests validate every case against it
src/goldset/              the library and the `gold` CLI: case store and hashing, runner,
                          evaluators, buckets, ledger (module map in CLAUDE.md)
tools/                    command-line tools over src/goldset (see tools/README.md)
templates/                HTML templates for the rendered reports
tests/                    the test suite; needs no network
results/runs/             the committed run ledger (contract: results/README.md)
results/reports/          rendered HTML reports (gitignored, regenerable)
results/recommendations/  one action doc per official run
results/artifacts/        raw agent state per case and trial (gitignored)
```

CI lives at the project-zeno root, not here: `.github/workflows/gold-ephemeral.yaml` runs this suite against an ephemeral per-commit deployment on push to main and on a PR's first non-draft state.

## Further reading

| Document | What it covers |
|---|---|
| [CLAUDE.md](CLAUDE.md) | Rules for AI coding agents working here (identity system, run rules, working agreements) and the module map |
| [cases/README.md](cases/README.md) | How to write a good case, the status lifecycle and the audit gate |
| [cases/v2/COVERAGE.md](cases/v2/COVERAGE.md) | Generated coverage report: groups, buckets, expected fields, datasets against the agent's catalogue, parked cases, known gaps |
| [src/goldset/evaluators/README.md](src/goldset/evaluators/README.md) | Reference for every check: what it reads, when it scores `null` or `0.0`, its bucket, and how to triage a failure |
| [results/README.md](results/README.md) | The ledger contract, comparing two runs, and composing a current picture across runs |
| [results/recommendations/](results/recommendations/) | One action doc per official run |
| [tools/README.md](tools/README.md) | Every command-line tool, grouped by what it works on |

## Note on this move

This directory was brought over from the standalone `gnw-gold-evals` repo so that changing the agent and fixing the cases it breaks can happen in the same PR, and so `--env local` runs need no separate checkout. Deliberately left behind as pure legacy, with nothing here depending on them: the frozen `cases/v1` sheet-import baseline, a handful of bridge tools for moving cases to/from the retired Google Sheet or comparing against the retired gnw-evals harness, and `.claude/skills/` (kept local to the original repo by choice). None of it is needed to run or extend this copy; see the original repo's history if one is ever needed.
