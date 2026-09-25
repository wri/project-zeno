"""Run description/instruction variants and save every answer.

usage: run.py <set: dev|holdout|holdout2> <runs> <variant> [<variant> ...]
       variant = <description>:<instruction>[:<none mode>], e.g. cards:short
Set ONLY=<backend name> to run one backend. Results are appended to
results/<backend>.jsonl (one line per case and run); run numbers continue
after the runs already saved for that variant and set.
"""

import json
import os
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from sets import M, dev_cases, holdout2_cases, holdout_cases
from variants import question

RESULTS = Path(__file__).with_name("results")
BACKENDS = [
    b
    for b in M["BACKENDS"]
    if b["api_key"] and os.environ.get("ONLY", b["name"]) == b["name"]
]
# api.codiv.ai returns 429 above ~2 parallel calls; OpenRouter does not.
WORKERS = {"codiv-open": 2, "openrouter": 6}


def call(client, backend, q, case):
    payload = {
        "model": backend["model"],
        "state": M["_state"](case),
        "questions": {"dataset": q},
    }
    for attempt in range(6):
        try:
            t0 = time.perf_counter()
            r = client.post(backend["path"], json=payload)
            dt = time.perf_counter() - t0
            r.raise_for_status()
            body = r.json()
            a = body["answers"]["dataset"]
            return {
                "choice": a.get("choice"),
                # Rounded, and near-zero choices dropped, to keep the
                # results files small enough to commit.
                "probs": {
                    k: round(v, 3)
                    for k, v in (a.get("probabilities") or {}).items()
                    if v >= 0.001
                },
                "conf": round(a["confidence"], 3)
                if a.get("confidence") is not None
                else None,
                "time": round(dt, 3),
                "cost": (body.get("usage") or {}).get("cost"),
            }
        except (httpx.HTTPError, KeyError) as exc:
            err = str(exc)
            time.sleep(3 * (attempt + 1))
    return {"choice": None, "error": err}


def main():
    which, runs, variants = sys.argv[1], int(sys.argv[2]), sys.argv[3:]
    cases = {
        "dev": dev_cases,
        "holdout": holdout_cases,
        "holdout2": holdout2_cases,
    }[which]()
    clients = {
        b["name"]: httpx.Client(
            base_url=b["base_url"],
            headers={"Authorization": f"Bearer {b['api_key']}"},
            timeout=120,
        )
        for b in BACKENDS
    }
    RESULTS.mkdir(exist_ok=True)
    for b in BACKENDS:
        out_path = RESULTS / f"{b['name']}.jsonl"
        done = defaultdict(set)  # (variant, set) -> run ids already saved
        if out_path.exists():
            for line in out_path.open():
                r = json.loads(line)
                done[(r["variant"], r["set"])].add(r["run"])
        with out_path.open("a") as out:
            for variant in variants:
                q = question(*variant.split(":"))
                for _ in range(runs):
                    run = max(done[(variant, which)], default=-1) + 1
                    done[(variant, which)].add(run)
                    with ThreadPoolExecutor(WORKERS[b["name"]]) as pool:
                        res = list(
                            pool.map(
                                lambda c: call(clients[b["name"]], b, q, c),
                                cases,
                            )
                        )
                    ok = 0
                    for c, r in zip(cases, res):
                        ok += r["choice"] == c["dataset"]
                        out.write(
                            json.dumps(
                                {
                                    "variant": variant,
                                    "run": run,
                                    "backend": b["name"],
                                    "set": c["set"],
                                    "id": c.get("id") or c["query"],
                                    "expected": c["dataset"],
                                    **r,
                                }
                            )
                            + "\n"
                        )
                    out.flush()
                    errs = sum(1 for r in res if r.get("error"))
                    print(
                        f"{variant:<16} run {run} {b['name']:<11} {ok}/{len(cases)}  errors={errs}",
                        flush=True,
                    )


if __name__ == "__main__":
    main()
