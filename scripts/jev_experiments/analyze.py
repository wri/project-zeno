"""Summarize results.jsonl.

usage: analyze.py [variant ...]     (default: all variants in results/)
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

NONE = "none"
rows = [
    json.loads(line)
    for path in sorted(Path(__file__).with_name("results").glob("*.jsonl"))
    for line in path.open()
]
wanted = sys.argv[1:]
if wanted:
    rows = [r for r in rows if r["variant"] in wanted]


def subset(r):
    if r["set"] in ("holdout", "holdout2"):
        return r["set"]
    return "gold_dev" if re.fullmatch(r"1-\d{3}", r["id"]) else "unit"


def pick(r, tau):
    """Fall back to the best non-none choice when p(none) < tau."""
    if r["choice"] != NONE or not r.get("probs") or tau <= 0:
        return r["choice"]
    if r["probs"].get(NONE, 1.0) >= tau:
        return NONE
    return max((k for k in r["probs"] if k != NONE), key=r["probs"].get)


groups = defaultdict(list)
for r in rows:
    groups[(r["variant"], r["backend"])].append(r)

TAUS = [0, 0.5, 0.6, 0.7, 0.8]
subsets = ["unit", "gold_dev", "holdout", "holdout2"]
print(
    f"{'variant':<16} {'backend':<11} {'runs':>4} "
    + " ".join(f"{s:>9}" for s in subsets)
    + f" {'all':>9} {'none ok':>8} {'false none':>10}  "
    + " ".join(f"tau{t:<4}" for t in TAUS[1:])
)
for (variant, backend), rs in sorted(groups.items()):
    runs = sorted({r["run"] for r in rs if r["set"] == "dev"})
    errs = sum(1 for r in rs if r.get("error"))

    def acc(sel, tau=0):
        """Mean correct per run and cases per run, over the selected rows.
        Runs are counted per subset, since subsets can have different runs."""
        sel_rows = [r for r in rs if sel(r)]
        if not sel_rows:
            return None
        n_runs = len({(subset(r), r["run"]) for r in sel_rows}) / len(
            {subset(r) for r in sel_rows}
        )
        vals = [pick(r, tau) == r["expected"] for r in sel_rows]
        return sum(vals) / n_runs, round(len(vals) / n_runs)

    cells = []
    for s in subsets:
        a = acc(lambda r, s=s: subset(r) == s)
        cells.append(f"{a[0]:5.1f}/{a[1]:<3}" if a else f"{'-':>9}")
    a = acc(lambda r: True)
    dev = [r for r in rs if r["set"] == "dev"]
    dev_runs = len({r["run"] for r in dev}) or 1
    none_ok = (
        sum(r["choice"] == NONE for r in dev if r["expected"] == NONE)
        / dev_runs
    )
    n_none = sum(1 for r in dev if r["expected"] == NONE) // dev_runs
    false_none = (
        sum(r["choice"] == NONE for r in dev if r["expected"] != NONE)
        / dev_runs
    )
    taus = [
        f"{acc(lambda r: r['set'] == 'dev', t)[0]:5.1f}  " for t in TAUS[1:]
    ]
    print(
        f"{variant:<16} {backend:<11} {len(runs):>4} "
        + " ".join(cells)
        + f" {a[0]:5.1f}/{a[1]:<3} {none_ok:4.1f}/{n_none:<3} {false_none:10.1f}  "
        + " ".join(taus)
        + (f"  errors={errs}" if errs else "")
    )
print(
    "\nruns = dev runs; none ok / false none are on dev (the holdouts have no 'none' rows)"
)
print(
    "tau columns: dev accuracy when a 'none' pick with p(none) < tau falls back to the best dataset"
)
