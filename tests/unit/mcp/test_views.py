"""The MCP Apps views: every tool points at a view the server serves, and
each view is one self-contained HTML document."""

import re
import shutil
import subprocess

import pytest
from fastmcp import Client

from src.mcp.server import mcp_server
from src.mcp.views import (
    SHARED_SCRIPTS,
    TOOL_VIEWS,
    UI_MIME_TYPE,
    VIEW_DIR,
    VIEWS,
    render_view,
    view_uri,
)


async def test_every_tool_points_at_a_served_view():
    async with Client(mcp_server) as client:
        tools = await client.list_tools()
        resources = {
            str(resource.uri): resource
            for resource in await client.list_resources()
        }
    for tool in tools:
        uri = tool.meta["ui"]["resourceUri"]
        assert uri == view_uri(TOOL_VIEWS[tool.name])
        assert resources[uri].mime_type == UI_MIME_TYPE


async def test_a_view_is_served_with_its_csp():
    async with Client(mcp_server) as client:
        [content] = await client.read_resource(view_uri("charts"))
    assert content.mime_type == UI_MIME_TYPE
    assert content.text == render_view("charts")
    csp = content.meta["ui"]["csp"]
    assert csp["resourceDomains"] == [
        "https://fonts.googleapis.com",
        "https://fonts.gstatic.com",
    ]


@pytest.mark.parametrize("name", list(VIEWS))
def test_a_view_inlines_its_css_and_scripts(name):
    page = render_view(name)
    _, script = VIEWS[name]
    for filename in ("base.css", *SHARED_SCRIPTS, script):
        # Each source is in the page, so the view needs no fetch of its own.
        assert (VIEW_DIR / filename).read_text().strip()[-200:] in page
    # The sandboxed iframe loads nothing but the fonts its CSP allows.
    assert not re.search(r"<script[^>]+src=", page)
    assert not re.search(r"<link[^>]+href=", page)
    hosts = set(re.findall(r"url\([\"']?(https?://[^/\"')]+)", page))
    assert hosts <= {"https://fonts.googleapis.com"}


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
@pytest.mark.parametrize("name", list(VIEWS))
def test_a_view_script_parses(name, tmp_path):
    page = render_view(name)
    script = page.split("<script>", 1)[1].rsplit("</script>", 1)[0]
    path = tmp_path / f"{name}.js"
    path.write_text(script)
    result = subprocess.run(
        ["node", "--check", str(path)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
