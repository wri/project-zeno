import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
CONTRACT_PACKAGE = "src.shared.imagery"
CONTRACT_MODULES = {"wire", "contract"}


def module_name(path: Path) -> str:
    return ".".join(path.relative_to(REPO).with_suffix("").parts)


def imported_modules(path: Path) -> set[str]:
    imported = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
            imported.update(
                f"{node.module}.{alias.name}" for alias in node.names
            )
    return imported


def specialists() -> list[str]:
    return [
        path.stem
        for path in (SRC / "shared" / "imagery").glob("*.py")
        if path.stem not in CONTRACT_MODULES
    ]


def allowed_importers(specialist: str) -> set[str]:
    return {f"{CONTRACT_PACKAGE}.wire", f"src.agent.imagery.{specialist}"}


def test_imagery_specialists_are_imported_only_by_the_wire_contract_and_their_own_provider():
    found = specialists()
    assert found

    violations = [
        f"{module_name(path)} imports {CONTRACT_PACKAGE}.{specialist}"
        for path in sorted(SRC.rglob("*.py"))
        for specialist in found
        if f"{CONTRACT_PACKAGE}.{specialist}" in imported_modules(path)
        and module_name(path) not in allowed_importers(specialist)
    ]

    assert not violations, "\n".join(violations)
