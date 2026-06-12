import json
from pathlib import Path

from src.agent.utils.sgrep import (
    _ROOT,
    _portable_path,
    _resolve_data_dir,
    data_status,
)

ARTICLE = """\
# Example Article

**URL:** https://www.wri.org/insights/example-article
**Last modified:** 2026-05-05T21:01Z

> Abstract text.
[§1] First paragraph.
"""


def _write_corpus(data_dir: Path, n_articles: int = 1) -> None:
    data_dir.mkdir(parents=True)
    articles = []
    for i in range(n_articles):
        slug = f"example-article-{i}"
        (data_dir / f"{slug}.md").write_text(ARTICLE, encoding="utf-8")
        articles.append({"slug": slug})
    (data_dir / "index.json").write_text(
        json.dumps({"articles": articles}), encoding="utf-8"
    )


def _write_index(index_dir: Path, n_chunks: int = 1) -> None:
    import numpy as np

    index_dir.mkdir(parents=True)
    np.save(
        index_dir / "embeddings.npy",
        np.zeros((n_chunks, 4), dtype=np.int8),
    )
    (index_dir / "meta.jsonl").write_text(
        "\n".join(
            json.dumps({"file": "example-article-0.md", "line": 1})
            for _ in range(n_chunks)
        ),
        encoding="utf-8",
    )
    (index_dir / "config.json").write_text(
        json.dumps({"scale": 1.0, "dim": 4, "data_dir": "data/wri_insights"}),
        encoding="utf-8",
    )


def test_portable_path_is_relative_inside_repo() -> None:
    assert _portable_path(_ROOT / "data" / "wri_insights") == str(
        Path("data") / "wri_insights"
    )


def test_portable_path_keeps_absolute_outside_repo() -> None:
    assert _portable_path(Path("/elsewhere/data")) == "/elsewhere/data"


def test_resolve_data_dir_resolves_relative_against_repo_root(
    tmp_path: Path,
) -> None:
    assert (
        _resolve_data_dir(str(tmp_path)) == tmp_path
    )  # existing absolute path is kept
    resolved = _resolve_data_dir("data/wri_insights")
    assert resolved.is_absolute()


def test_data_status_ok(tmp_path: Path) -> None:
    data_dir = tmp_path / "corpus"
    index_dir = tmp_path / "index"
    _write_corpus(data_dir, n_articles=2)
    _write_index(index_dir, n_chunks=3)

    ok, detail = data_status(data_dir=data_dir, index_dir=index_dir)
    assert ok
    assert "2 articles" in detail
    assert "3 indexed paragraphs" in detail


def test_data_status_missing_corpus(tmp_path: Path) -> None:
    ok, detail = data_status(
        data_dir=tmp_path / "nope", index_dir=tmp_path / "index"
    )
    assert not ok
    assert "missing article corpus" in detail


def test_data_status_too_few_articles(tmp_path: Path) -> None:
    data_dir = tmp_path / "corpus"
    _write_corpus(data_dir, n_articles=1)
    ok, detail = data_status(
        data_dir=data_dir, index_dir=tmp_path / "index", min_articles=10
    )
    assert not ok
    assert "expected >= 10" in detail


def test_data_status_missing_index(tmp_path: Path) -> None:
    data_dir = tmp_path / "corpus"
    _write_corpus(data_dir)
    ok, detail = data_status(data_dir=data_dir, index_dir=tmp_path / "index")
    assert not ok
    assert "missing sgrep index file" in detail


def test_data_status_inconsistent_index(tmp_path: Path) -> None:
    data_dir = tmp_path / "corpus"
    index_dir = tmp_path / "index"
    _write_corpus(data_dir)
    _write_index(index_dir, n_chunks=2)
    (index_dir / "meta.jsonl").write_text(
        json.dumps({"file": "example-article-0.md", "line": 1}),
        encoding="utf-8",
    )
    ok, detail = data_status(data_dir=data_dir, index_dir=index_dir)
    assert not ok
    assert "inconsistent" in detail
