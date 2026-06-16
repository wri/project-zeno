#!/usr/bin/env python3
"""Pull/push the WRI Insights corpus + sgrep index as a single S3 tarball.

The snapshot lives at ``$WRI_INSIGHTS_S3_URI`` (e.g. ``s3://bucket/prefix/``):

    <prefix>/latest.tar.gz     current snapshot (consumed by builds, seeds the cron)
    <prefix>/<YYYY.MM.DD>.tar.gz  dated archive

The tarball bundles ``wri_insights/`` and ``wri_insights_index/`` so it extracts
straight into ``data/``. Gzip is used so Python's stdlib ``tarfile`` can unpack
it with no extra tooling in the app image.
"""

from __future__ import annotations

import argparse
import io
import os
import sys
import tarfile
import time
from urllib.parse import urlparse

import boto3

from src.agent.utils.sgrep import DEFAULT_DATA_DIR, DEFAULT_INDEX_DIR

_DATA_ROOT = DEFAULT_DATA_DIR.parent
_PAYLOAD_DIRS = (DEFAULT_DATA_DIR, DEFAULT_INDEX_DIR)
_LATEST_KEY = "latest.tar.gz"
_ENV_VAR = "WRI_INSIGHTS_S3_URI"


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    """Split ``s3://bucket/prefix/`` into ``(bucket, prefix)`` (no leading/
    trailing slash on the prefix)."""
    parsed = urlparse(uri)
    if parsed.scheme != "s3" or not parsed.netloc:
        raise ValueError(f"not an s3:// URI: {uri!r}")
    return parsed.netloc, parsed.path.strip("/")


def _key(prefix: str, name: str) -> str:
    return f"{prefix}/{name}" if prefix else name


def pull() -> int:
    uri = os.environ.get(_ENV_VAR, "").strip()
    if not uri:
        print(f"{_ENV_VAR} not set; skipping pull (local build).")
        return 0

    bucket, prefix = _parse_s3_uri(uri)
    key = _key(prefix, _LATEST_KEY)
    client = boto3.client("s3")
    try:
        obj = client.get_object(Bucket=bucket, Key=key)
    except client.exceptions.NoSuchKey:
        print(f"No snapshot at s3://{bucket}/{key}; nothing to seed.")
        return 0

    _DATA_ROOT.mkdir(parents=True, exist_ok=True)
    with tarfile.open(
        fileobj=io.BytesIO(obj["Body"].read()), mode="r:gz"
    ) as tar:
        tar.extractall(_DATA_ROOT)
    print(f"Extracted s3://{bucket}/{key} into {_DATA_ROOT}")
    return 0


def push() -> int:
    uri = os.environ.get(_ENV_VAR, "").strip()
    if not uri:
        print(f"{_ENV_VAR} not set; cannot push snapshot.", file=sys.stderr)
        return 1

    missing = [d for d in _PAYLOAD_DIRS if not d.exists()]
    if missing:
        names = ", ".join(str(d) for d in missing)
        print(f"Missing payload dirs: {names}", file=sys.stderr)
        return 1

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path in _PAYLOAD_DIRS:
            tar.add(path, arcname=path.name)
    data = buf.getvalue()

    bucket, prefix = _parse_s3_uri(uri)
    date_key = _key(
        prefix, f"{time.strftime('%Y.%m.%d', time.gmtime())}.tar.gz"
    )
    latest_key = _key(prefix, _LATEST_KEY)
    client = boto3.client("s3")
    for key in (date_key, latest_key):
        client.put_object(Bucket=bucket, Key=key, Body=data)
        print(f"Uploaded s3://{bucket}/{key} ({len(data) / 1e6:.1f} MB)")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser(
        "pull", help="download + extract latest snapshot into data/"
    )
    sub.add_parser("push", help="tar data/ payload dirs and upload to S3")
    args = parser.parse_args()

    sys.exit(pull() if args.command == "pull" else push())


if __name__ == "__main__":
    main()
