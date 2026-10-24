# gnw-cli

Global Nature Watch data on the command line, as files an analysis can
repeat. It is meant for coding agents (Claude Code, Codex, Gemini CLI) and
the people who work with them: chat clients use the GNW MCP server
instead.

```sh
uv tool install "git+https://github.com/wri/project-zeno#subdirectory=cli"
gnw skill install                     # .claude/skills/gnw-cli and gnw-charting
gnw areas "Pará, Brazil"
gnw datasets 4
gnw pull --aoi gadm:BRA.14_1 --dataset 4 --start 2015-01-01
gnw charts --aoi gadm:BRA.14_1 --dataset 4 --start 2015-01-01
gnw replay
```

A pull lands in `gnw/pulls/<result_id>/`: `rows.csv`, `request.json`,
`provenance.json` and `pull.py`, the standalone script that fetches the
same rows again. The CLI writes the folder by running that script, so what
is on disk is what the script repeats. `gnw replay` runs every script again
and reports the pulls whose rows changed, writing their new rows to
`rows.changed.csv` and leaving `rows.csv` as it was.

Every command calls a tool of the GNW MCP server (`src/mcp/` in this
repository); the CLI holds no GNW logic of its own. Point it at another
server with `--server` or `GNW_MCP_URL`, e.g. `http://localhost:8000/mcp`
with `make api` running.

`src/gnw_cli/skill/SKILL.md` is the `gnw-cli` agent skill: the workflow,
the files, and what every answer ends with. `gnw skill install` writes it
next to the server's `gnw-charting` skill, whose `generators/run.py` draws
GNW's curated charts from a `rows.csv` without the server (needs numpy).
