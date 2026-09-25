"""Dev and holdout case sets for the jev description experiments.

dev      = CASES + GOLD_CASES from scripts/jev_dataset_test.py (89 cases,
           used to tune and compare the variants)
holdout  = HOLDOUT in holdout_cases.py (51 GOLD sheet rows)
holdout2 = HOLDOUT2 in holdout_cases.py (38 rows from other eval files)
"""

import runpy
from pathlib import Path

from dotenv import load_dotenv
from holdout_cases import HOLDOUT, HOLDOUT2

REPO = Path(__file__).resolve().parents[2]
# The app settings read .env at import time; load it before importing the
# script. Shell values win over .env values.
load_dotenv(REPO / ".env")
M = runpy.run_path(str(REPO / "scripts/jev_dataset_test.py"))
NONE, KEYS = M["NONE"], M["KEYS"]


def dev_cases():
    return [dict(c, set="dev") for c in M["CASES"] + M["GOLD_CASES"]]


def holdout_cases():
    return [dict(c, set="holdout") for c in HOLDOUT]


def holdout2_cases():
    return [dict(c, set="holdout2") for c in HOLDOUT2]


if __name__ == "__main__":
    from collections import Counter

    for name, fn in [
        ("dev", dev_cases),
        ("holdout", holdout_cases),
        ("holdout2", holdout2_cases),
    ]:
        cases = fn()
        print(name, len(cases), dict(Counter(c["dataset"] for c in cases)))
