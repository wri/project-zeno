from importlib.metadata import PackageNotFoundError, version


def get_version() -> str:
    try:
        return version("project-zeno")
    except PackageNotFoundError:
        # Fallback for environments where the package is not installed
        import tomllib
        from pathlib import Path

        root = Path(__file__).parent.parent.parent
        with open(root / "pyproject.toml", "rb") as f:
            return tomllib.load(f)["project"]["version"]
