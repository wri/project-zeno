"""goldset: the GOLD regression suite for the GNW agent.

Case store, runner, checks (evaluators and buckets) and the results ledger.
"""

from goldset.canonical import case_uid, caseset_version
from goldset.store import Case, build_manifest, load_store, read_case, write_case

__all__ = [
    "Case",
    "build_manifest",
    "case_uid",
    "caseset_version",
    "load_store",
    "read_case",
    "write_case",
]
