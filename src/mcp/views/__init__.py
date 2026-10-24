"""Views: the HTML that an MCP Apps host draws for a tool's result.

A host that supports the MCP Apps extension (`io.modelcontextprotocol/ui`)
reads the `ui://` resource a tool names in `_meta.ui.resourceUri` and shows
it in a sandboxed iframe next to the tool call. The view receives the tool's
arguments and result over postMessage and draws them in GNW's style: area
cards, dataset cards, tables and the curated charts. A host without the
extension ignores the metadata and shows the tool's text, as before.

Each view is one self-contained HTML document: the shared CSS and scripts
in this folder are inlined, so the view needs no network except the IBM
Plex fonts, which its CSP allows and which fall back to system fonts.
"""

from functools import cache
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.apps.config import (
    UI_MIME_TYPE,
    AppConfig,
    ResourceCSP,
    ResourcePermissions,
    app_config_to_meta_dict,
)
from fastmcp.resources import TextResource

VIEW_DIR = Path(__file__).parent

SHARED_SCRIPTS = ("bridge.js", "components.js", "charts.js", "reproduce.js")

# View name → (title, script).
VIEWS = {
    "areas": ("GNW areas", "areas.js"),
    "datasets": ("GNW datasets", "datasets.js"),
    "data": ("GNW data", "data.js"),
    "charts": ("GNW curated charts", "charts-view.js"),
    "code": ("GNW chart code", "code.js"),
}

# Tool name → the view that draws its result.
TOOL_VIEWS = {
    "resolve_areas": "areas",
    "search_areas": "areas",
    "list_datasets": "datasets",
    "get_dataset": "datasets",
    "pull_data": "data",
    "curated_charts": "charts",
    "get_chart_code": "code",
}

VIEW_CSP = ResourceCSP(
    resource_domains=[
        "https://fonts.googleapis.com",
        "https://fonts.gstatic.com",
    ]
)
VIEW_PERMISSIONS = ResourcePermissions(clipboard_write={})

_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
{css}
</style>
</head>
<body>
<main id="app"></main>
<script>
{script}
</script>
</body>
</html>
"""


def view_uri(name: str) -> str:
    return f"ui://gnw/{name}.html"


def _read(filename: str) -> str:
    return (VIEW_DIR / filename).read_text(encoding="utf-8")


@cache
def render_view(name: str) -> str:
    """The HTML document of a view, with its CSS and scripts inlined."""
    title, script = VIEWS[name]
    scripts = [_read(filename) for filename in (*SHARED_SCRIPTS, script)]
    return _PAGE.format(
        title=title,
        css=_read("base.css"),
        script="\n".join(scripts),
    )


def tool_app(tool_name: str) -> AppConfig | None:
    """The `app` metadata that points a tool at its view."""
    view = TOOL_VIEWS.get(tool_name)
    return AppConfig(resource_uri=view_uri(view)) if view else None


def register_views(server: FastMCP) -> None:
    """Serve every view as a `ui://gnw/<name>.html` resource."""
    meta = {
        "ui": app_config_to_meta_dict(
            AppConfig(
                csp=VIEW_CSP,
                # The Reproduce panel's Copy buttons write to the clipboard.
                permissions=VIEW_PERMISSIONS,
                prefers_border=False,
            )
        )
    }
    for name, (title, _) in VIEWS.items():
        server.add_resource(
            TextResource(
                uri=view_uri(name),
                name=f"{name}_view",
                title=title,
                description=f"The MCP Apps view of the {name} tools.",
                text=render_view(name),
                mime_type=UI_MIME_TYPE,
                meta=meta,
            )
        )
