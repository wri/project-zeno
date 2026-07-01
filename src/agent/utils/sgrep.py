"""
sgrep - semantic grep for markdown.

    sgrep index              index default data dir
    sgrep index --data DIR   index a custom data dir
    sgrep "query"            search default index
    sgrep "query" --top N    return top N results (default: 10)

Defaults:
    --data   data/wri_insights
    --index  data/wri_insights_index
"""

import argparse
import json
import re
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np
from model2vec import StaticModel

_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA_DIR = _ROOT / "data" / "wri_insights"
DEFAULT_INDEX_DIR = _ROOT / "data" / "wri_insights_index"
MODEL_NAME = "minishlab/potion-retrieval-32M"

# Citation-tagged paragraph: [§N] or [§N | Section: "..."], optionally
# linkified as [...](url#pN)
TAG_RE = re.compile(
    r'^\[§(?P<para>\d+)(?:\s*\|\s*Section:\s*"(?P<section>[^"]*)")?\]'
    r"(?:\([^)]*\))?\s*(?P<text>.*)$"
)


@lru_cache(maxsize=2)
def get_model(local_dir: str | None = None) -> StaticModel:
    """Load the embedding model lazily on first use.

    int8 query vectors are >0.999 cosine-identical to float32 and shrink
    the bundled model from 125MB to 32MB.
    """
    return StaticModel.from_pretrained(
        local_dir or MODEL_NAME, quantize_to="int8"
    )


def _index_model(index_dir: Path) -> StaticModel:
    """Prefer the model copy bundled with the index (offline, and guaranteed
    to match the embeddings); fall back to the Hugging Face hub."""
    bundled = index_dir / "model"
    return get_model(str(bundled)) if bundled.is_dir() else get_model()


def normalize(v):
    return v / np.clip(np.linalg.norm(v, axis=-1, keepdims=True), 1e-12, None)


def paragraphs(text):
    """Yield (start_line, paragraph) for each blank-line-separated block."""
    para, start = [], None
    for n, line in enumerate(text.split("\n"), 1):
        if line.strip():
            start = start or n
            para.append(line)
        elif para:
            yield start, " ".join(para)
            para, start = [], None
    if para:
        yield start, " ".join(para)


def chunks(text):
    """Yield (line, para, section, text) chunks for one document.

    Documents with citation-tagged paragraphs ([§N](url#pN), one per line)
    are chunked by tag, with the link markup stripped from the text so it
    doesn't pollute the embeddings; untagged lines (title, URL header,
    abstract) are skipped. Documents without tags fall back to
    blank-line-separated paragraphs with para/section set to None.
    """
    tagged = []
    for n, line in enumerate(text.split("\n"), 1):
        m = TAG_RE.match(line)
        if m and m.group("text").strip():
            tagged.append(
                (n, int(m.group("para")), m.group("section"), m.group("text"))
            )
    if tagged:
        yield from tagged
    else:
        for line, para_text in paragraphs(text):
            yield line, None, None, para_text


def _portable_path(path: Path) -> str:
    """Render a path relative to the repo root so the index survives moves."""
    try:
        return str(path.relative_to(_ROOT))
    except ValueError:
        return str(path)


def _resolve_data_dir(raw: str) -> Path:
    """Resolve a config.json data_dir written by any checkout of the repo."""
    data_dir = Path(raw)
    if not data_dir.is_absolute():
        data_dir = _ROOT / data_dir
    if not data_dir.exists():  # index moved with the repo
        data_dir = DEFAULT_DATA_DIR
    return data_dir


def data_status(
    data_dir: Path = DEFAULT_DATA_DIR,
    index_dir: Path = DEFAULT_INDEX_DIR,
    min_articles: int = 1,
) -> tuple[bool, str]:
    """Report whether the article corpus and sgrep index are usable.

    Returns (ok, detail). Used by the Docker build and API startup to fail
    loudly when an image was built without the data snapshot, instead of
    erroring on the first search query.
    """
    index_json = data_dir / "index.json"
    if not index_json.exists():
        return False, f"missing article corpus at {data_dir}"
    n_articles = len(
        json.loads(index_json.read_text(encoding="utf-8")).get("articles", [])
    )
    if n_articles < min_articles:
        return False, (
            f"corpus at {data_dir} has {n_articles} articles "
            f"(expected >= {min_articles})"
        )
    for name in ("embeddings.npy", "meta.jsonl", "config.json"):
        if not (index_dir / name).exists():
            return False, f"missing sgrep index file {index_dir / name}"
    n_chunks = np.load(index_dir / "embeddings.npy", mmap_mode="r").shape[0]
    n_meta = sum(
        1
        for line in (index_dir / "meta.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    )
    if n_chunks != n_meta:
        return False, (
            f"sgrep index inconsistent: {n_chunks} embeddings "
            f"vs {n_meta} meta entries in {index_dir}"
        )
    return True, (
        f"{n_articles} articles in {data_dir}, "
        f"{n_chunks} indexed paragraphs in {index_dir}"
    )


def build_index(data_dir: Path, index_dir: Path):
    meta, texts = [], []
    for path in sorted(data_dir.rglob("*.md")):
        for line, para, section, text in chunks(
            path.read_text(encoding="utf-8")
        ):
            meta.append(
                {
                    "file": str(path.relative_to(data_dir)),
                    "line": line,
                    "para": para,
                    "section": section,
                }
            )
            texts.append(text)

    model = get_model()
    emb = normalize(model.encode(texts)).astype("float32")
    # int8-quantize with a single symmetric scale; chunk text is not stored
    # (it is reconstructed from the source files at query time).
    scale = float(np.abs(emb).max() / 127.0) or 1.0
    q8 = np.round(emb / scale).clip(-127, 127).astype(np.int8)

    index_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(index_dir / "model")
    np.save(index_dir / "embeddings.npy", q8)
    (index_dir / "config.json").write_text(
        json.dumps(
            {
                "scale": scale,
                "dim": int(emb.shape[1]),
                "data_dir": _portable_path(data_dir),
            }
        ),
        encoding="utf-8",
    )
    (index_dir / "meta.jsonl").write_text(
        "\n".join(json.dumps(m, ensure_ascii=False) for m in meta),
        encoding="utf-8",
    )
    print(
        f"indexed {len(texts)} paragraphs from {len({m['file'] for m in meta})} files -> {index_dir}"
    )


def paint(s, code):
    return f"\033[{code}m{s}\033[0m" if sys.stdout.isatty() else str(s)


@lru_cache(maxsize=256)
def _chunk_texts(path_str: str) -> dict:
    """Map a source file's chunk key (para or 'L<line>') to its text."""
    out = {}
    for line, para, _section, text in chunks(
        Path(path_str).read_text(encoding="utf-8")
    ):
        out[para if para is not None else f"L{line}"] = text
    return out


def _chunk_text(data_dir: Path, m: dict) -> str:
    key = m["para"] if m.get("para") is not None else f"L{m['line']}"
    return _chunk_texts(str(data_dir / m["file"])).get(key, "")


@lru_cache(maxsize=4)
def _load_index(
    index_dir_str: str,
) -> tuple[np.ndarray, list[dict], float, Path]:
    """Load and cache the embedding matrix, metadata, and config for an index.

    Converts int8 → float32 once so every query_index call avoids the 123 MB
    per-call allocation that mmap + asarray would otherwise produce.
    """
    index_dir = Path(index_dir_str)
    emb = np.load(index_dir / "embeddings.npy").astype("float32")
    config = json.loads(
        (index_dir / "config.json").read_text(encoding="utf-8")
    )
    meta = [
        json.loads(line)
        for line in (index_dir / "meta.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    return emb, meta, config["scale"], _resolve_data_dir(config["data_dir"])


def query_index(
    index_dir: Path, query: str, k: int = 10, threshold: float = 0.3
) -> list[dict]:
    """Return the top-k matching paragraphs as a list of result dicts."""
    emb, meta, scale, data_dir = _load_index(str(index_dir))
    qv = normalize(_index_model(index_dir).encode([query])[0]).astype(
        "float32"
    )
    scores = (emb @ qv) * scale

    results = []
    for i in np.argsort(-scores)[:k]:
        if scores[i] < threshold:
            break
        m = meta[i]
        results.append(
            {
                "file": m["file"],
                "line": m["line"],
                "para": m.get("para"),
                "section": m.get("section"),
                "score": float(scores[i]),
                "text": _chunk_text(data_dir, m),
            }
        )
    return results


def search(index_dir: Path, query: str, k: int = 10, threshold: float = 0.3):
    last = None
    for r in query_index(index_dir, query, k=k, threshold=threshold):
        if r["file"] != last:
            print(f"\n{paint(r['file'], 35)}")
            last = r["file"]
        loc = f"§{r['para']}" if r.get("para") else str(r["line"])
        print(
            f"{paint(loc, 32)}:{paint(f'{r["score"]:.2f}', 33)}: {r['text'][:120]}"
        )


def main():
    parser = argparse.ArgumentParser(
        prog="sgrep",
        description="semantic grep for markdown",
    )
    sub = parser.add_subparsers(dest="cmd")

    idx = sub.add_parser("index", help="build the search index")
    idx.add_argument(
        "--data",
        type=Path,
        default=DEFAULT_DATA_DIR,
        metavar="DATA_DIR",
        help=f"markdown source directory (default: {DEFAULT_DATA_DIR})",
    )
    idx.add_argument(
        "--index",
        type=Path,
        default=DEFAULT_INDEX_DIR,
        metavar="INDEX_DIR",
        help=f"index storage directory (default: {DEFAULT_INDEX_DIR})",
    )

    srch = sub.add_parser("search", help="search the index")
    srch.add_argument("query", help="search query")
    srch.add_argument(
        "--index",
        type=Path,
        default=DEFAULT_INDEX_DIR,
        metavar="INDEX_DIR",
        help=f"index storage directory (default: {DEFAULT_INDEX_DIR})",
    )
    srch.add_argument(
        "--top",
        type=int,
        default=10,
        metavar="N",
        help="number of results (default: 10)",
    )
    srch.add_argument(
        "--threshold",
        type=float,
        default=0.3,
        help="minimum similarity score (default: 0.3)",
    )

    # allow bare `sgrep "query"` without the search subcommand
    if len(sys.argv) > 1 and sys.argv[1] not in (
        "index",
        "search",
        "-h",
        "--help",
    ):
        sys.argv.insert(1, "search")

    args = parser.parse_args()

    if args.cmd == "index":
        build_index(args.data.resolve(), args.index.resolve())
    elif args.cmd == "search":
        search(
            args.index.resolve(),
            args.query,
            k=args.top,
            threshold=args.threshold,
        )
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
