# tools/: the CLI surface

Terms are defined in the [README glossary](../README.md#glossary).

Thin CLIs over `src/goldset/` (each adds `src/` to `sys.path` itself). Run
any of them as `uv run python tools/<tool>.py`; `--help` prints its usage.
The harness itself is the `gold` command (`uv run gold run`, see
[Running the set](../README.md#running-the-set)). No tool hand-writes a
ledger entry: [results/README.md](../results/README.md) has the contract
they all follow.

## Case store

| tool | what it does |
|---|---|
| `check.py` | Verify the case store: every uid matches its case, every case is valid, and the manifest is current. Run `--fix` after any case edit to recompute uids and the manifest; CI runs plain `check.py` on both stores. Part of the [after-edit steps](../README.md#changing-cases). |
| `audit_cases.py` | Check the case set against the authoring rules in `cases/README.md`: depth, coverage floors and the DON'T list. Run it before opening a case PR. CI runs it with `--strict`, which fails on depth and DON'T violations (see [the audit gate](../cases/README.md#the-audit-gate)). |
| `coverage_doc.py` | Regenerate `cases/v2/COVERAGE.md` from the store and the catalogue snapshot. Run it after any case edit or catalogue sync, and commit the result with the edit; CI's `--check` fails if the committed file is out of date. |
| `sync_zeno_catalog.py` | Refresh `cases/zeno_catalog.json`, the committed snapshot of project-zeno's dataset catalogue (dataset ids, dataset-specific parameters, context layers, instruction fields) that COVERAGE.md measures against. It also carries each dataset's analytics endpoint and date window, from which ground-truth requests are built. Run it when project-zeno adds, removes or changes a dataset. It reads `origin/main` of this same repo (gold lives inside project-zeno; `--zeno` for another path), so the snapshot stays pinned to a committed ref rather than a dirty working tree. Then run `coverage_doc.py`. |

## Results ledger

| tool | what it does |
|---|---|
| `diff_runs.py` | Count regressions, recoveries, data bumps and coverage changes between two runs, over the cases both scored. Use it after an official run, against the last comparable run, and as the release gate (`--fail-on-regression`, optionally `--fail-on-coverage-loss`). A ground-truth check that flips while the digest of its fetched values moved is a **data bump**: listed, never gating, and flagged when it may hide a real regression. Only diff runs that are comparable as defined in [Comparing two runs](../results/README.md#comparing-two-runs). |
| `find_baseline.py` | Print the newest run in `results/runs/` that matches a given run on environment, `ff`, trial count and case store (`caseset`), never the run itself; exit non-zero with the reason when none matches. The CI release gate uses it to pick the run it diffs against. |
| `flakiness.py` | For one multi-trial run, each check's mean, standard deviation and flip count across trials (`--per-case` lists the cases that flapped). Use it after every official run, and before calling a regression real, to see whether the check just flaps. Partial samples are flagged INSUFFICIENT DATA. |
| `compose_runs.py` | When a scoped re-run has refreshed some rows of a full run, combine the two into one current picture without editing either run file. Each row shows which run it came from; nothing is written to `results/runs/` (see [Composing](../results/README.md#composing-a-current-picture-across-runs)). |

## Reports

| tool | what it does |
|---|---|
| `report_run.py` | Markdown summary of one run on stdout: row verdicts, the bucket table, implied against evaluated checks (the reconciliation line), and diagnostics such as judge errors and slow rows. Use it for a quick read in the terminal or to paste into a PR. |
| `render_html.py` | Standalone HTML report of one run for stakeholders; `--all` builds the cross-run page with a run selector. Refresh both after every official run. |
| `render_inspector.py` | HTML matrix of every case against every check, with expected and measured values. Use it to find which checks failed on which cases; `--all` builds the cross-run page. |
| `render_trends.py` | Pass-rate trends across every run in the ledger, one line per `ff`. Use it to see movement across releases; never read a trend across differing `ff`. |

## After-run ritual

The steps after every official run (render the reports, check flakiness and
diff, write the recommendations doc, commit) are in the root README under
[After a run](../README.md#after-a-run).
