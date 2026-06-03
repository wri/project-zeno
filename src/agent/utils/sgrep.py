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
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np
from model2vec import StaticModel

_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA_DIR = _ROOT / "data" / "wri_insights"
DEFAULT_INDEX_DIR = _ROOT / "data" / "wri_insights_index"
MODEL_NAME = "minishlab/potion-retrieval-32M"


@lru_cache(maxsize=1)
def get_model() -> StaticModel:
    """Load the embedding model lazily on first use."""
    return StaticModel.from_pretrained(MODEL_NAME)


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


def build_index(data_dir: Path, index_dir: Path):
    meta, texts = [], []
    for path in sorted(data_dir.rglob("*.md")):
        for line, text in paragraphs(path.read_text(encoding="utf-8")):
            meta.append(
                {
                    "file": str(path.relative_to(data_dir)),
                    "line": line,
                    "text": text,
                }
            )
            texts.append(text)

    emb = normalize(get_model().encode(texts)).astype("float32")
    index_dir.mkdir(parents=True, exist_ok=True)
    np.save(index_dir / "embeddings.npy", emb)
    (index_dir / "meta.jsonl").write_text(
        "\n".join(json.dumps(m, ensure_ascii=False) for m in meta),
        encoding="utf-8",
    )
    print(
        f"indexed {len(texts)} paragraphs from {len({m['file'] for m in meta})} files -> {index_dir}"
    )


def paint(s, code):
    return f"\033[{code}m{s}\033[0m" if sys.stdout.isatty() else str(s)


def query_index(
    index_dir: Path, query: str, k: int = 10, threshold: float = 0.3
) -> list[dict]:
    """Return the top-k matching paragraphs as a list of result dicts."""
    emb = np.load(index_dir / "embeddings.npy", mmap_mode="r")
    meta = [
        json.loads(line)
        for line in (index_dir / "meta.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    scores = np.asarray(emb @ normalize(get_model().encode([query])[0]))

    results = []
    for i in np.argsort(-scores)[:k]:
        if scores[i] < threshold:
            break
        m = meta[i]
        results.append(
            {
                "file": m["file"],
                "line": m["line"],
                "score": float(scores[i]),
                "text": m["text"],
            }
        )
    return results


def search(index_dir: Path, query: str, k: int = 10, threshold: float = 0.3):
    last = None
    for r in query_index(index_dir, query, k=k, threshold=threshold):
        if r["file"] != last:
            print(f"\n{paint(r['file'], 35)}")
            last = r["file"]
        print(
            f"{paint(r['line'], 32)}:{paint(f'{r['score']:.2f}', 33)}: {r['text'][:120]}"
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
