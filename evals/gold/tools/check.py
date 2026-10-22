"""Verify (or repair) case-store integrity: uids, validity, manifest.

    uv run python tools/check.py          # verify; nonzero exit on drift (CI)
    uv run python tools/check.py --fix    # recompute uids + manifest after edits

After hand-editing a case YAML, run `check.py --fix`: the case's uid then
identifies its new content, and the manifest's caseset_version moves with
it. This is only the first step of the after-edit ritual: finish it
(README.md, "Changing cases") before committing, or CI fails on a stale
COVERAGE.md.

uids follow the store's `uid_includes_deltas` manifest flag. When it is set
(cases/v2, the current store), each multi-turn case's deltas are hashed
into its uid. `--fix --uid-includes-deltas` turns the flag on for a store
and rewrites its uids; `--fix` alone keeps whatever the manifest records.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from goldset.store import (
    build_manifest,
    load_store,
    read_manifest,
    store_uid_includes_deltas,
    write_case,
    write_manifest,
)
from goldset.templates import validate_templates


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--cases-dir", type=Path, default=Path("cases/v2"))
    parser.add_argument("--fix", action="store_true")
    parser.add_argument(
        "--uid-includes-deltas",
        action="store_true",
        help="with --fix: record uid_includes_deltas in this store's manifest "
        "and rehash its multi-turn uids over each turn's deltas (one-way; "
        "never use on a store whose uids must stay as imported)",
    )
    args = parser.parse_args()
    if args.uid_includes_deltas and not args.fix:
        parser.error("--uid-includes-deltas changes identities; it needs --fix")

    uid_includes_deltas = args.uid_includes_deltas or store_uid_includes_deltas(
        args.cases_dir
    )
    entries = load_store(args.cases_dir, uid_includes_deltas)
    if not entries:
        print(f"no cases found under {args.cases_dir}")
        return 1

    problems: list[str] = []
    for path, case, stored_uid in entries:
        problems += case.validate()
        queries = (
            [turn["query"] for turn in case.turns]
            if case.is_multiturn
            else [case.query]
        )
        for query in queries:
            for issue in validate_templates(query):
                problems.append(f"{path}: {issue}")
        if stored_uid != case.uid:
            if args.fix:
                write_case(args.cases_dir, case)
                print(f"fixed uid: {path} {stored_uid or '(none)'} -> {case.uid}")
            else:
                problems.append(f"{path}: stored uid {stored_uid!r} != {case.uid}")

    ids = [case.id for _p, case, _u in entries]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        problems.append(f"duplicate case ids: {duplicates}")

    cases = [case for _p, case, _u in entries]
    manifest_on_disk = read_manifest(args.cases_dir)
    source = (manifest_on_disk or {}).get("source", "unknown")
    manifest = build_manifest(cases, source, uid_includes_deltas)
    if manifest_on_disk != manifest:
        if args.fix:
            write_manifest(args.cases_dir, manifest)
            print(
                f"manifest regenerated, caseset_version={manifest['caseset_version']}"
            )
        else:
            problems.append("manifest is stale (run check.py --fix)")

    if problems:
        print("FAIL:", *problems, sep="\n  ")
        return 1
    print(f"ok: {len(entries)} cases, caseset_version={manifest['caseset_version']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
