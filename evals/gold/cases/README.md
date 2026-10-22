# Writing GOLD cases: what makes a good prompt

GOLD is a **capability smoke test**. A case earns its place by failing when
a release breaks a capability and passing otherwise. Everything below
follows from that one job. Read this file before you add or edit a case.

Terms are defined in the [README glossary](../README.md#glossary). A case
is one YAML file at `cases/<store>/<group>/<id>.yaml`.
`schema/case.schema.json` defines its fields, and the
[check index](../src/goldset/evaluators/README.md#index) says which
`expected` key switches on which check. The commands to run after any edit
are in [README: Changing cases](../README.md#changing-cases).

## The case store

`cases/v2/` is the one curated store: every edit and every new case lands
here. It has its own `MANIFEST.json` holding its
[caseset_version](../README.md#caseset-version), and a run records the
store (`caseset`) and caseset_version it loaded. A v2 [uid](../README.md#uid)
hashes a multi-turn case's `deltas` too, so editing one mints a new version
same as any other expected-value edit.

## The four properties of a good case

1. **Capability-anchored.** It exercises one nameable thing the product
   does. If the case fails, an engineer knows which subsystem to look at;
   that is what `group:` means.
2. **Deterministic.** It fails only when the agent changes, never because
   time passed, data was updated or a judge changed its mind.
3. **Checkable in depth.** Its expectations imply at least two checks in at
   least two [buckets](../README.md#bucket) (Retrieval, Analysis,
   Explanation, Output, Scope), so a pass can't mean "measured nothing".
   CI enforces this ([The audit gate](#the-audit-gate)).
4. **Environment-honest.** If the capability is missing in some environment
   or [profile](../README.md#profile), the case carries an `env_gated` note
   so its zeros are never read as agent regressions. Today the LGMS dataset
   (id 12) exists only on the `experimental` profile, so its cases are
   parked while runs use the default profile. Re-check `env_gated` notes
   when the environment changes: older notes saying that dashboards or
   imagery need `--ff experimental` are out of date
   ([Running the set](../README.md#running-the-set)).

## DOs

- **DO use absolute, closed date windows.** ✔ `"…between January 2025 and
  April 2025…"` with `start_date: '2025-01-01'`, `end_date: '2025-04-30'`.
  Reserve date expectations for datasets that are actually date-scoped
  (see the DON'Ts).
- **DO give every case a `scope`**: `analyse`, `suggest`, `clarify` or
  `refuse`, matching whether the agent pulled data, offered a dataset
  choice, asked which one, or did neither. It's the cheapest deterministic
  check in the suite — one key, read straight off the final state. A
  clarifying question asked in plain prose, with no nudge, still counts as
  `refuse`.
- **DO name the metric unambiguously** — the class, the gas basis, the
  confidence tier. ✔ `"gross greenhouse gas emissions from tree cover
  loss"` ✘ `"deforestation-related carbon emissions"`. Precise wording cuts
  dataset-choice nudges from 38% of trials to 1.2% (measured over 312
  trials), and a single nudge fails five to seven checks at once.
- **DO add a framing clause when only one of two similar datasets gives
  the intended answer.** ✔ `"Distinguishing natural from non-natural land
  cover, …"` routes to SBTN Natural Lands over Global Land Cover without
  naming either. Left unsteered, the agent may nudge between them and fail
  the case. If both datasets would give the same answer, accept both
  instead (next rule).
- **DO use `;`-alternatives when two answers are genuinely defensible and
  equally correct**, instead of rewording the prompt to force one.
  `dataset_id: "<a>;<b>"` accepts either dataset; `scope: "refuse;suggest"`
  accepts either behaviour. Pinning a single value on a row that could
  defensibly go either way just makes a case that fails at random — note
  why both are accepted in `notes` (some fields read `;` as "all of",
  not "either": see [below](#semicolons)).
- **DO keep a few cases with deliberately loose wording.** Without them,
  nothing catches a regression toward over-nudging, since precisely worded
  rows only test whether the agent nudges when it should. A loosely
  worded row uses `;`-alternatives covering every defensible dataset and
  `scope: analyse`, so it fails only on an unwanted nudge. None exist
  today — note any you add in `notes.sentinel` so it isn't tightened away
  by accident.
- **DO put per-class figures in `class_values`** when the query implies a
  breakdown. ✔ `class_values: "mangroves=15,444 hectares"` catches a wrong
  sub-total hiding under a correct headline. The check behind it is
  currently [info-only](../README.md#info-only) (reported, never gating),
  so add a verified `answer` too if the row needs a gating check.
- **DO write behaviour expectations in `text`** for terminology, caveats
  and refusals. ✔ `text: "resolution of tree cover loss is 30 x 30 meters"`
  ✔ `text: "refuses monthly analysis because the dataset is annual"`. The
  judge behind this check is the most stable in the suite.
- **DO name the admin level when the AOI is ambiguous.** ✔ `"…in Puri
  district, Odisha, India"` — or expect a clarification instead. An
  ambiguous AOI with a pinned expectation flaps, since the agent can
  resolve it differently from trial to trial. Check that a multi-area AOI
  (e.g. "protected areas in Colorado") resolves consistently before
  pinning an expectation to it.

## DON'Ts

- **DON'T name the dataset by id or product name.** ✘ `"Using the SBTN
  Natural Lands Map…"` hands over the answer and turns `dataset_id_match`
  into a copy-paste test. Exception: groups whose subject *is* the
  dataset (`dataset-parameters`, `dataset-suggestion`, `context-layer`,
  `dashboard`).
- **DON'T use relative dates.** ✘ `"…in the past decade"`, ✘ `"…since
  2020"`: the true answer moves with every data release. A routing-only
  query (no `answer`, `text` or dates expected) can tolerate it, and a
  query that genuinely needs the current period should use a template
  token like `{current_month}` instead — the harness fills it in at run
  time and the uid still hashes consistently (`src/goldset/templates.py`).
- **DON'T set date expectations on annual datasets** (tree cover loss and
  the other yearly ones). The agent pulls the full range and slices in
  code, so the recorded window flips between runs while the answer stays
  right — let `answer` carry the year instead. Date-scoped datasets
  (integrated alerts, the `imagery` group) are the exception.
- **DON'T stake a verdict on chart choice.** Chart type is the agent's
  least deterministic output — 8 of 19 flaky rows in one 3-trial run were
  chart-type flakes. If it matters, expect alternatives:
  `chart_type: "bar;table"`.
- **DON'T pin expectations that drift with data versions.** ✘ "the most
  recent year is 2024" breaks on the next data release — use a closed
  period on a stable dataset instead. Better still, don't pin the number
  at all: use `ground_truth` so the harness fetches it at run time.
- **DON'T write a case with only `answer` or `text` and no other
  expectation.** Both are scored by the LLM judge, so a case with nothing
  else has no deterministic check in code to confirm the judge got it
  right — it's only as reliable as that one judge call. The `metadata`
  group is the sanctioned exception: a dataset-documentation question like
  "what's the resolution of this dataset?" has no AOI, dataset or number
  to check, only a description to judge.
- **DON'T write multi-turn turns whose text depends on the agent's
  previous wording.** ✔ `"Puri in Odisha, India"` works whatever the
  clarification said; ✘ `"yes, the first option"` depends on option order.
- **DON'T edit `expected` casually.** Changing the query or any expected
  value mints a new [uid](../README.md#uid), resetting the case's
  regression history, and a `done` case needs re-verifying at the new one.
  The uid hashes every expected field, scored or not, so don't move
  expectations into `notes` just to dodge a new uid — batch edits together
  and explain them in the PR.

<a id="semicolons"></a>
## `;` alternatives by field

A `;` inside an expected value does not mean the same thing in every
field. Check this table before you write one.

| Field | `a;b` means | How it is matched |
|---|---|---|
| `dataset_id` | any of | the dataset the agent chose (and, for `pull_source_match`, the one it pulled) must be one of the alternatives |
| `scope` | any of | the observed scope must be one of them; one invalid alternative makes the check abstain |
| `nudge_type` | any of | the nudge's type must be one of them |
| `chart_type` | any of | the first chart's type must be one of them |
| `aoi_ids` | all of | the set of resolved AOI ids must equal the expected set exactly (GADM ids are compared without their `_N` suffix); there is no way to write "either of these places" |
| `class_values` | all of | every `name=value` pair must match within the 2% tolerance |
| `dashboard_widgets` | all of, with counts | widget types are compared as a multiset: `insight;insight;map` means exactly two insight widgets and one map widget |
| `nudge_options` | allowed set | the agent must offer at least one option, and every option it offers must match one in the list (case-insensitive substring, either way round) |
| `suggested_datasets` | allowed set | as `nudge_options`; legacy, because the agent no longer writes this state field |
| any other field (`answer`, `text`, dates, ...) | nothing special | the value is used whole. In `answer` the judge reads `a;b` as written, so a reply that merely names both values can pass |

## Run-time ground truth (`ground_truth`)

A numeric case can name **which figure** it is about instead of **what value**
that figure has. The harness fetches the number from the analytics API before
any trial runs, so the case survives every data release with its uid — and its
regression history — intact.

```yaml
expected:
  aoi_ids: MDG.3.4_1
  aoi_source: gadm
  dataset_id: '4'
  ground_truth: sum(carbon_emissions_MgCO2e) WHERE tree_cover_loss_year=2019
  chart_type: bar
  scope: analyse
```

**Grammar** — `AGG(column)` or `AGG(column) WHERE column=value`, with `AGG` one
of `sum`, `max`, `min`, `count`. An explicit aggregate is **mandatory**: a bare
column would be ambiguous whenever the filter matches more than one row, which
is live (1-059 pulls 254 areas).

**No new request fields.** The request is built from expectations the case
already carries — `aoi_ids`, `aoi_source`, `dataset_id`, `context_layer`,
`dataset_parameters`, `start_date`, `end_date` — because a GOLD case already
asserts what query the agent should build. `ground_truth` is purely the
*response* side.

**Four rules, each with a case behind it:**

1. **The selector names the API's column, not the agent's.** The agent renames
   columns in its pandas codeact — 1-076's chart says `loss_area_ha` where the
   API says `area_ha` — so authoring from an artifact's `charts_data` is a trap.
   Read column names from project-zeno's `src/api/services/charts.py`, or from a
   raw `source_url` response.
2. **The metric is often not the obvious column.** 1-046 asks for "tonnes of
   CO2", which is `carbon_emissions_MgCO2e`. Picking `area_ha` would compare
   658,571 against 1,371.15 and report a 99.8% miss as an agent failure.
3. **On annual datasets the year goes in the selector, not the request.** The
   DON'T above still applies: the case carries no dates, the request uses the
   catalog's full window, and `WHERE tree_cover_loss_year=2019` does the
   narrowing.
4. **Spell the selector canonically**: lowercase aggregate function name,
   uppercase `WHERE`, unquoted filter value, no padding inside the expression:
   `sum(area_ha) WHERE year=2019`. Both spellings parse, but the **raw string is
   hashed into the uid**, so `where` and `WHERE` would mint two uids for the
   same test. `tools/audit_cases.py` enforces this and fails `--strict` on a
   selector that is spelled differently or does not parse at all; surrounding
   whitespace is stripped before hashing and is not flagged.

**The migration cost:**

1. **New uid.** Adding `expected.ground_truth` mints a new uid and restarts the
   case's history.
2. **Fewer checks.** `agent_answer`, `charts_answer` and `chart_produced` only
   run when `expected.answer` is present in the YAML, so removing that removes
   these checks. They are replaced by `ground_truth_match`, which is
   deterministic. The other new check is `ground_truth_answer`, which is
   informative only and never fails a row, since a gating check has to be
   deterministic.

The area identity must be explicit and resolvable: the fetch will not geocode
from the prompt, because that would redo the agent's own AOI resolution and let
an AOI regression silently corrupt the ground truth. A case with no `aoi_ids` or
no `aoi_source` aborts the run rather than guessing.

## Worked examples

Each example quotes a real case file, without its `uid` and `notes`. If you
edit one of these cases, update the quote here.

**A good single-turn case** (`cases/v2/direct/1-002.yaml`):

```yaml
id: 1-002
status: done
group: direct
query: How much of Sao Paulo was affected by disturbance alerts in the second half of 2024,
  considering high and highest confidence alerts only?
expected:
  aoi_ids: BRA.25_1
  aoi_source: gadm
  dataset_id: '11'
  dataset_name: Integrated alerts
  start_date: '2024-07-01'
  end_date: '2024-12-31'
  answer: 1,299,278 hectares
  scope: analyse
```

- It names a state (no AOI ambiguity), the confidence tiers (one reading of
  the metric) and a closed window on a date-scoped dataset, so the answer
  is stable.
- Its expectations imply eight checks across all five buckets:
  `aoi_id_match`, `dataset_id_match`, `date_extraction`,
  `data_pull_exists`, `answered_without_data`, `agent_answer`,
  `chart_produced` and `scope_match`. `aoi_source` and `dataset_name` imply
  none, though both are hashed into the uid.
- The expected number came from a real run and sits well inside the 2%
  tolerance. A figure 1.5% off the agent's stable answer would flip to a
  hard failure on the next data refresh with nothing else changed.

**A bad case and its repair** (`cases/v2/direct/1-075.yaml`, before and
after):

```yaml
# before: parked
id: 1-075
status: not doing
group: direct
query: How much tree cover loss within intact forest landscapes in Sweden since 2020?
expected:
  aoi_ids: SWE
  dataset_id: '4'
  dataset_name: Tree cover loss
  context_layer: intact_forest
  answer: 3.3 kha
  scope: analyse

# after: repaired and verified
id: 1-075
status: done
group: direct
query: How much tree cover loss occurred within intact forest landscapes in Sweden between
  2020 and 2024?
expected:
  aoi_ids: SWE
  dataset_id: '4'
  dataset_name: Tree cover loss
  context_layer: intact_forest
  answer: 391.70 hectares
  scope: analyse
  aoi_source: gadm
```

"Since 2020" is an open window, so the true figure grows with every data
release. Closing it to 2020 to 2024 fixes the answer, and the new figure
was measured on a 3-trial run (391.70 ha on all three trials). The old
`3.3 kha` had never been verified, and it was wrong.

**A multi-turn case** (`cases/v2/multiturn/mt-005.yaml`):

```yaml
id: mt-005
status: ready
group: multiturn
turns:
- query: How much tree cover loss did Brazil have in 2022?
  expected:
    aoi_ids: BRA
    dataset_id: '4'
    scope: analyse
- query: And for Indonesia?
  expected:
    aoi_ids: IDN
    scope: analyse
  deltas:
    changed:
    - aoi_ids
    retain:
    - dataset_id
```

All turns share one thread, and turn 2's text works whatever turn 1's reply
said. Its `deltas` assert how the state moved since the previous turn:
`changed` (the field must differ), `retain` (it must stay the same, which
catches lost context) and `absent` (it must be empty, which catches
carry-over). Each turn with `deltas` adds a `state_delta` check; the
allowed field names are listed in `schema/case.schema.json`.

## Status lifecycle

Every case has one of four statuses:

- `ready`: written and expected to pass, but not yet verified at its current uid.
- `todo`: held by a known problem; a dated `notes.status_reason` says what blocks it.
- `done`: verified at its current uid (see below).
- `not doing`: parked; runs skip it, and `notes.status_reason` says why.

`gold run` runs every status except `not doing` (`--status-exclude`
defaults to `not doing`), and the audit and COVERAGE.md count the same
cases as active. So `ready` and `todo` cases are run and scored like
`done` ones; the progress line prints each case's status, so a failure on
an unverified case reads differently. COVERAGE.md lists every `todo` and
`not doing` case with its reason
([Parked and held cases](v2/COVERAGE.md#parked-and-held-cases)).

**Promoting to `done`.** A case is `done` when it passes at its current
uid on a 3-trial run with the same `ff` as the release baseline (today the
default [profile](../README.md#profile), no `--ff`): every gating check
that ran passed on the majority of the three [trials](../README.md#trial).
Cite the run_id and date in `notes.status_reason`, for example
`promoted to done <date>: passed at this uid on run <run_id> (3 trials, default profile)`.
A 1-trial pass is a smoke signal, not verification. An edit that mints a
new uid ends the verification: set the case back to `ready` until it
passes again.

**Parking.** Set `status: not doing` when a case cannot earn a verdict,
and always write a dated `notes.status_reason` with the evidence: which
run, what the agent did on how many trials, and why no prompt edit can fix
it (or what would). `cases/v2/parent-child/1-011.yaml` has a good example.
Notes are never hashed, so parking does not change the uid.

**Unparking.** Treat it as probation: re-test the reason the case was
parked, and do not assume it is fixed. An edit that does not touch that
reason (closing the date window on a case parked for an ambiguous AOI,
say) leaves the case parked. An unparked case returns as `ready` (or
`todo`) and earns `done` like any other.

## Mechanics checklist (every case PR)

- [ ] the four properties hold, and the expectations imply at least two
      checks in at least two buckets
- [ ] `env_gated` noted if the capability depends on the environment or profile
- [ ] the status follows the [status lifecycle](#status-lifecycle); a `done`
      case cites its verifying run
- [ ] the after-edit commands in [README: Changing cases](../README.md#changing-cases)
      ran clean, and their output is committed with the case
- [ ] `uv run pytest tests/test_schema.py -q` passes (the file matches the schema)
- [ ] if you edited a case quoted in [Worked examples](#worked-examples), the
      quote is updated
- [ ] the PR text says *why* the semantics changed (the uid change records *what*)

## The audit gate

CI runs `uv run python tools/audit_cases.py --strict` on every PR and every
push to `main`. It checks every active case in v2 (any status but
`not doing`, and every turn of a multi-turn case) and **fails the build**
on two kinds of defect, both fixable in the case you are already editing:

- **Depth violations**: a case whose expectations imply fewer than two
  checks, or checks in fewer than two buckets. A row like that can "pass"
  while measuring almost nothing, and an unmeasured bucket must look
  different from a passing one. The usual fix is a verified `answer`, which
  implies checks in Retrieval, Analysis, Explanation and Output at once;
  `scope` adds only Scope. The audit counts info-only checks too, so
  `class_values` satisfies it without adding a gating check. The `metadata`
  group is exempt.
- **DON'T violations** (`dont_violations` in `tools/audit_cases.py`):
  - relative-date words (`last`, `past`, `recent`, `latest`, `this year`,
    `this month`, `this week`) in a query whose expectations go beyond
    routing;
  - `start_date` or `end_date` on a dataset that is not date-scoped (with
    `;`-alternatives, every alternative must be date-scoped);
  - judged-only expectations (`answer` or `text` with no deterministic
    field and, on a multi-turn turn, no `deltas`) outside the `metadata`
    group;
  - an unknown `{template}` token in a query.

Deliberately **not** gated: the coverage floors (groups or datasets with
fewer than three active cases). Clearing those means authoring new cases,
which is different work from fixing the one in front of you, so they stay
report-only. The report is still worth reading.

Run the audit before you open a PR; it takes about a second and is the
same command CI runs.

**A green audit is not proof.** The relative-date rule matches a fixed
list of words, so phrasings like "since 2020" or "since the turn of the
century" pass the audit even when paired with an `answer`. Read the rule,
not just the exit code.
