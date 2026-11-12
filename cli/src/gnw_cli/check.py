"""Check a server's pull.py before the CLI runs it.

The CLI runs the pull.py a server returns, and the server may be any URL
(`--server`, `$GNW_MCP_URL`). So it runs a script only when it is GNW's
template (`pull_template.txt`, rendered from `src/mcp/script.py` with empty
data) with nothing changed but the docstring and the data: the request, the
provenance, the area names and the default folder, each of them a literal or
`json.loads` of a string. Any other code is refused.
"""

import ast
from importlib import resources

# The template's data: what one pull's script holds that another's does not.
DATA_NAMES = frozenset(
    {"REQUEST", "PROVENANCE", "AREA_NAMES", "DEFAULT_FOLDER"}
)


def _template() -> list[ast.stmt]:
    text = (resources.files("gnw_cli") / "pull_template.txt").read_text(
        encoding="utf-8"
    )
    return ast.parse(text).body


def _is_docstring(node: ast.stmt) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def _is_data(value: ast.expr) -> bool:
    """A literal, or `json.loads("<a string>")`."""
    if (
        isinstance(value, ast.Call)
        and ast.dump(value.func)
        == ast.dump(ast.parse("json.loads", mode="eval").body)
        and len(value.args) == 1
        and not value.keywords
        and isinstance(value.args[0], ast.Constant)
        and isinstance(value.args[0].value, str)
    ):
        return True
    try:
        ast.literal_eval(value)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return False
    return True


def _data_name(node: ast.stmt) -> str | None:
    if (
        isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id in DATA_NAMES
    ):
        return node.targets[0].id
    return None


def is_gnw_script(script: str) -> bool:
    """True when `script` is GNW's pull.py template with only its
    docstring and data filled in."""
    try:
        body = ast.parse(script).body
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        return False
    template = _template()
    if len(body) != len(template):
        return False
    for i, (node, expected) in enumerate(zip(body, template)):
        if i == 0 and _is_docstring(node) and _is_docstring(expected):
            continue
        name = _data_name(expected)
        if name is not None:
            if _data_name(node) != name or not _is_data(node.value):
                return False
            continue
        if ast.dump(node) != ast.dump(expected):
            return False
    return True
