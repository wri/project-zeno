import os
import re
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


def get_commit() -> str | None:
    """The git commit this build runs, from GIT_SHA (set by the Docker
    build); None when it is not set, as in local runs."""
    sha = os.getenv("GIT_SHA", "").strip().lower()
    return sha if re.fullmatch(r"[0-9a-f]{7,40}", sha) else None
