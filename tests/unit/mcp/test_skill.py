"""The gnw-charting skill: checked in, built from the catalog and the
generators, and served by the MCP server."""

from fastmcp import Client

from src.mcp.server import mcp_server
from src.mcp.skill import SKILL_DIR, build_skill


def test_the_checked_in_skill_matches_its_sources():
    built = build_skill()
    on_disk = {
        path.relative_to(SKILL_DIR).as_posix(): path.read_text("utf-8")
        for path in SKILL_DIR.rglob("*")
        if path.is_file()
    }
    stale = sorted(
        path
        for path in built.keys() | on_disk.keys()
        if built.get(path) != on_disk.get(path)
    )
    assert (
        not stale
    ), f"Stale skill files {stale}: run `uv run python -m src.mcp.skill`."


def test_the_skill_covers_every_dataset_the_server_offers():
    files = build_skill()
    skill = files["SKILL.md"]
    assert skill.startswith("---\nname: gnw-charting\ndescription: ")
    datasets = [path for path in files if path.startswith("datasets/")]
    assert len(datasets) == 11
    assert all(path in skill for path in datasets)
    # LGMS is hidden from the server, so from its skill too.
    assert "LGMS" not in skill
    tcl = files["datasets/04-tree-cover-loss.md"]
    for heading in (
        "## Curated charts",
        "## How to chart it",
        "## How to present it",
        "## Cautions",
        "## Colors",
        "## Citation",
    ):
        assert heading in tcl
    assert "(../generators/tcl.py)" in tcl
    assert "class TCLChartGenerator" in files["generators/tcl.py"]


async def test_the_server_serves_the_skill():
    async with Client(mcp_server) as client:
        uris = {str(r.uri) for r in await client.list_resources()}
        main = await client.read_resource("skill://gnw-charting/SKILL.md")
        tcl = await client.read_resource(
            "skill://gnw-charting/datasets/04-tree-cover-loss.md"
        )
    assert "skill://gnw-charting/generators/tcl.py" in uris
    assert "## Workflow" in main[0].text
    assert tcl[0].text.startswith("# Tree cover loss (dataset 4)")
