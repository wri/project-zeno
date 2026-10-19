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
"""

from __future__ import annotations

import json
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

It needs Python 3.9 or later and nothing else. The analytics API gives the
same request the same result id, so the script warns when it answers with
a result other than {result_id}.

{citation}
"""

import csv
import json
import os
import shutil
import sys
import time
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
        answer, retry_after = call("GET", link)
        job = answer.get("data") or {{}}
        status = job.get("status")
        if status in ("success", "saved"):
            return link, job["result"]
        if status in ("failed", "error"):
            sys.exit(f"The analytics API failed: {{job.get('message')}}")
        if time.monotonic() > deadline:
            sys.exit(f"Timed out waiting for {{link}}")
        time.sleep(wait_seconds(retry_after))


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
    if PROVENANCE["result_id"] and result_id != PROVENANCE["result_id"]:
        print(
            f"Warning: the analytics API answered with result {{result_id}}, "
            f"not {{PROVENANCE['result_id']}}. The data may have changed.",
            file=sys.stderr,
        )

    folder.mkdir(parents=True, exist_ok=True)
    write_csv(rows, folder / "rows.csv")
    write_json(REQUEST, folder / "request.json")
    write_json(
        {{
            **PROVENANCE,
            "replayed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "replayed_result_id": result_id,
            "replayed_source_url": link,
        }},
        folder / "provenance.json",
    )
    script = Path(__file__).resolve()
    if script != (folder / "pull.py").resolve():
        shutil.copyfile(script, folder / "pull.py")
    print(f"{{len(rows)}} rows written to {{folder / 'rows.csv'}}")


if __name__ == "__main__":
    main()
'''


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
