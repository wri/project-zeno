"""pull.py: a standalone script that replays one pull.

`pull_data` and `curated_charts` return it with every pull. It holds the
request that AnalyticsHandler sent to the analytics API, as the handler
recorded it, so the script and the server cannot drift apart: the script
does not rebuild the request, it sends the same one again. It then shapes
the rows the way `run_pull` does (area names, the same sort order) and
writes them to a folder with the request and the pull's provenance.

The script needs Python and nothing else, so anyone can run it without
zeno or the MCP server. A test runs it against a stub API and checks that
it writes the rows the server returned.

The analytics API files a request under an id made from the request itself,
so a data release answers the same request under the same id. The pull's
`rows_sha256` (`rows_digest`) is what tells a replay whether the rows
changed: the script computes it the same way and compares.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from pprint import pformat
from textwrap import fill
from typing import TYPE_CHECKING, Optional

from src.shared.geocoding_helpers import format_id
from src.shared.version import get_version

if TYPE_CHECKING:
    from src.mcp.data import Pull

_TEMPLATE = '''\
"""{heading}

Replays the request the Global Nature Watch MCP server (version
{version}) sent to the GNW analytics API on {retrieved_at}, and
writes what the API returns to a folder:

- rows.csv: the rows, as the MCP server returned them
- request.json: the request this script sends
- provenance.json: the areas, dates and options of the pull
- pull.py: a copy of this script

    python pull.py [folder]    # default: {folder}

It needs Python 3.9 or later and nothing else. It warns when the rows
differ from the ones the MCP server returned (the data was updated), or
when the API files the request under an id other than {result_id} (it
reads the request differently). Changed rows never overwrite a folder's
rows.csv: they go to rows.changed.csv and provenance.changed.json, so the
rows an analysis was built on stay to compare with.

{citation}
"""

import csv
import hashlib
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REQUEST = {request}

PROVENANCE = {provenance}

# The analytics API returns area ids; these are the names the MCP server
# gave them.
AREA_NAMES = {area_names}

DEFAULT_FOLDER = {folder!r}
TIMEOUT_SECONDS = 180


def call(method, url, body=None):
    """One request to the analytics API; the JSON answer and Retry-After."""
    headers = {{"Accept": "application/json", **REQUEST["headers"]}}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    # Only needed for endpoints that ask for a token.
    token = os.environ.get("WRI_BEARER_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {{token}}"
    request = urllib.request.Request(
        url, data=data, headers=headers, method=method
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response), response.headers.get("Retry-After")


def wait_seconds(retry_after):
    try:
        return float(retry_after)
    except (TypeError, ValueError):
        return 1.0


def fetch():
    """Send the request, then read its result link until the job is done."""
    answer, _ = call(REQUEST["method"], REQUEST["url"], REQUEST["body"])
    link = answer["data"]["link"]
    deadline = time.monotonic() + TIMEOUT_SECONDS
    while True:
        retry_after = None
        try:
            answer, retry_after = call("GET", link)
        except (OSError, ValueError):
            # A failed poll (an HTTP error, a dropped connection, a broken
            # answer) is tried again until the deadline, as the server does.
            answer = {{}}
        job = answer.get("data") or {{}}
        status = job.get("status")
        if status in ("success", "saved"):
            return link, job["result"]
        if status in ("failed", "error"):
            sys.exit(f"The analytics API failed: {{job.get('message')}}")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            sys.exit(f"Timed out waiting for {{link}}")
        time.sleep(min(wait_seconds(retry_after), remaining))


def to_rows(result):
    """The API's columns as rows, named and sorted as the server does."""
    columns = dict(result)
    if "aoi_id" in columns:
        columns["name"] = [
            AREA_NAMES.get(str(aoi_id), aoi_id) for aoi_id in columns["aoi_id"]
        ]
    keys = list(columns)
    rows = [dict(zip(keys, values)) for values in zip(*columns.values())]
    if not rows:
        return rows
    # By area, then by any year or date column.
    order = ["name"] + [
        key for key in rows[0] if "year" in key.lower() or "date" in key.lower()
    ]
    order = [key for key in order if key in rows[0]]

    def sort_key(row):
        return tuple(
            (row.get(key) is None, row.get(key) if row.get(key) is not None else 0)
            for key in order
        )

    try:
        return sorted(rows, key=sort_key)
    except TypeError:
        return rows


def rows_digest(rows):
    """The SHA-256 of the rows as canonical JSON, as the MCP server makes
    it: equal rows give equal digests."""
    text = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_csv(rows, path):
    columns = {{}}
    for row in rows:
        columns.update(dict.fromkeys(row))
    with open(path, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file, fieldnames=list(columns), lineterminator="\\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def write_json(value, path):
    with open(path, "w", encoding="utf-8") as file:
        json.dump(value, file, indent=2, ensure_ascii=False)
        file.write("\\n")


def main():
    folder = Path(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_FOLDER)
    link, result = fetch()
    rows = to_rows(result)
    result_id = link.rstrip("/").rsplit("/", 1)[-1]
    digest = rows_digest(rows)
    changed = digest != PROVENANCE["rows_sha256"]
    # Keep the rows an analysis was built on: changed rows go beside them.
    keep = changed and (folder / "rows.csv").exists()
    suffix = ".changed" if keep else ""
    if changed:
        print(
            "Warning: the rows differ from the ones the MCP server returned "
            f"on {{PROVENANCE['retrieved_at']}}. The data may have been updated."
            + (
                f" The new rows are in {{folder / 'rows.changed.csv'}}; "
                "rows.csv is unchanged."
                if keep
                else ""
            ),
            file=sys.stderr,
        )
    if PROVENANCE["result_id"] and result_id != PROVENANCE["result_id"]:
        print(
            f"Warning: the analytics API filed the request as {{result_id}}, "
            f"not {{PROVENANCE['result_id']}}. It reads the request differently now.",
            file=sys.stderr,
        )

    folder.mkdir(parents=True, exist_ok=True)
    rows_path = folder / f"rows{{suffix}}.csv"
    write_csv(rows, rows_path)
    write_json(REQUEST, folder / "request.json")
    write_json(
        {{
            **PROVENANCE,
            "replayed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "replayed_result_id": result_id,
            "replayed_source_url": link,
            "replayed_rows_sha256": digest,
        }},
        folder / f"provenance{{suffix}}.json",
    )
    script = Path(__file__).resolve()
    if script != (folder / "pull.py").resolve():
        shutil.copyfile(script, folder / "pull.py")
    print(f"{{len(rows)}} rows written to {{rows_path}}")


if __name__ == "__main__":
    main()
'''


def rows_digest(rows: list[dict]) -> str:
    """The SHA-256 of `rows` as canonical JSON. pull.py has a copy; the
    two must agree, which test_script checks by running the script."""
    text = json.dumps(
        rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _literal(value) -> str:
    """`value` as a Python expression: its JSON, so it reads like
    request.json; a plain Python literal when the JSON would not fit in a
    raw string."""
    text = json.dumps(value, indent=4, ensure_ascii=False)
    if "'''" in text:
        return pformat(value, sort_dicts=False)
    return f"json.loads(\n    r'''\n{text}\n'''\n)"


def _wrap(text: str) -> str:
    """Docstring text, wrapped without breaking URLs."""
    text = text.replace("\\", "/").replace('"""', "'''")
    return fill(text, 76, break_long_words=False, break_on_hyphens=False)


def pull_script(pull: Pull) -> Optional[str]:
    """The pull.py source for `pull`, or None when no request was recorded."""
    if not pull.request:
        return None
    provenance = {
        key: value
        for key, value in pull.provenance().items()
        if key != "request"
    }
    # The names the analytics handler adds to the rows: the area's name up
    # to the first comma, by the id the API knows it by.
    area_names = {
        format_id(area["aoi_id"].split(":", 1)[1]): area["name"].split(",")[0]
        for area in pull.areas
    }
    result_id = provenance["result_id"] or "latest"
    citation = " ".join(str(pull.ds.get("citation", "")).split())
    return _TEMPLATE.format(
        heading=_wrap(pull.heading()),
        version=get_version(),
        retrieved_at=pull.retrieved_at,
        folder=f"gnw/pulls/{result_id}",
        result_id=result_id,
        citation=_wrap(f"Citation: {citation}"),
        request=_literal(pull.request),
        provenance=_literal(provenance),
        area_names=_literal(area_names),
    )


# The gnw CLI runs a server's pull.py only when it matches this template
# (cli/src/gnw_cli/check.py), so the CLI ships a copy rendered with no data.
# test_script fails while the copy is stale.
CLI_TEMPLATE = (
    Path(__file__).resolve().parents[2]
    / "cli"
    / "src"
    / "gnw_cli"
    / "pull_template.txt"
)


def cli_template() -> str:
    """The template as the CLI checks scripts against it: no data."""
    return _TEMPLATE.format(
        heading="",
        version="",
        retrieved_at="",
        folder="gnw/pulls/latest",
        result_id="latest",
        citation="",
        request=_literal({}),
        provenance=_literal({}),
        area_names=_literal({}),
    )


if __name__ == "__main__":
    CLI_TEMPLATE.write_text(cli_template(), encoding="utf-8")
    print(f"Wrote {CLI_TEMPLATE}")
