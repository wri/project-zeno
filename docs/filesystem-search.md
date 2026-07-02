# Searching with the filesystem

We needed our agent to answer questions from a corpus of WRI Insights blog
articles — hundreds of markdown files, a few paragraphs each. Classic
needle-in-a-haystack: the answer is one or two paragraphs buried somewhere in
the pile.

This is an experiment to replace RAG with the filesystem, instead of the
embedding stores we use elsewhere (e.g. dataset search). Here's how we do it.

## The filesystem is the tool

No vector DB, no document store, no chunking service. The corpus is just a
folder of `.md` files on disk:

```
data/wri_insights/
  index.json        # metadata: slug, title, abstract, url, lastmod
  <slug>.md         # one article per file, full text
  ...
```

We fetch articles straight from WRI's sitemap, extract the body with
trafilatura, tag every paragraph with a citation anchor (`[§N](url#pN)`), and
write it to disk. That's it — the article store is a directory you can `ls`,
`cat`, and `grep`.

The agent gets a `FilesystemBackend` pointed at that folder, so it can `read_file`
any article and read `index.json` for metadata. The directory layout does the
work a database schema usually does, and it stays simple to inspect, diff, and
version.

The actual search agent's loop is: search a couple of times → shortlist →
read only what looks promising → answer. Two search tools feed that shortlist.

## ripgrep — exact search, first

The first search tool is plain `grep` (ripgrep under the hood). It's perfect for
the things that have to match *exactly*:

- names, places, acronyms (`CDR`, `COP28`)
- numbers and units
- specific terminology you already know is in the text

It's fast, zero setup, no model, no index. For a lot of queries this alone finds
the needle. We let the model run a few grep searches per question — trying a
couple of different phrasings of what the user asked — and collect the candidate
slugs across all of them.

The catch: grep only finds what you literally typed. Ask about "renewable energy
in Africa" and an article that says "solar capacity across the Sahel" won't
match, even though it's exactly what you wanted.

## sgrep — semantic search, as an add-on

That gap is why we added `sgrep` — semantic grep. It sits *on top of* grep, not
instead of it. Same idea (search the filesystem, return `file:line` hits you can
read), but it matches on **meaning** instead of characters.

How it works:

- We split every article into paragraphs and embed them with a small static
  retrieval model — `minishlab/potion-retrieval-32M` from Minish Labs
  (model2vec). Static embeddings mean no GPU, no inference server — it's
  basically a lookup table, so encoding the whole corpus and answering a query
  are both near-instant.
- The index is just two files on disk: `embeddings.npy` (a NumPy array) and
  `meta.jsonl`. Query = embed the query string, take a dot product against the
  matrix, return the top-k paragraphs above a similarity threshold.
- Output looks exactly like grep — `<file>:<line> (<score>): <text>` — so the
  agent treats both tools the same way and feeds both into the same shortlist.

So the division of labor is: grep nails the exact terms, sgrep catches the
paraphrases. Run both, union the candidates, read the promising ones. Cheap,
local, and good at the needle-in-haystack case.

## Why not a Recursive Language Model?

We also tried a Recursive Language Model (RLM) — handing the model the corpus
as a variable and letting it recurse over it to find the relevant passages itself.
Accuracy was about the same as grep + sgrep, but it cost considerably more tokens to do
the same job: the model reads much more of the haystack to find the needle, on
every query.

grep + sgrep reach the same answers by doing the retrieval outside the model —
the LLM only ever sees the handful of paragraphs that already matched. Same
quality, but less tokens. So that's the pattern we are keeping for now: filesystem as
the store, ripgrep for exact matches, sgrep for semantic matches, and the model
only reads what survived the shortlist.

## Deployment

The corpus and index are gitignored, so they have to reach production some
other way. We build them in an ephemeral job, store them as a single tarball
in S3, and bake that into the app image:

- The `ingest-blog-data` workflow (`.github/workflows/ingest-blog-data.yml`)
  runs weekly (and on demand): it seeds `data/` from the previous snapshot,
  fetches new/changed WRI and LCL articles, rebuilds the sgrep index, and
  uploads the result to `$WRI_INSIGHTS_S3_URI` as `latest.tar.gz` plus a dated
  `YYYY.MM.DD.tar.gz`. The runner is ephemeral — nothing is published as an
  image. Both ends use `scripts/wri_insights_snapshot.py` (`pull`/`push`).
- The app `Dockerfile` runs `scripts/wri_insights_snapshot.py pull` (AWS creds
  passed as build secrets) to download + extract the snapshot into `/app/data`,
  pre-downloads the `potion-retrieval-32M` embedding model into `HF_HOME`
  inside the image (no Hugging Face egress at runtime), and fails the build
  if the snapshot is missing or inconsistent (`sgrep.data_status`).
- The API logs the same `data_status` check at startup, so a pod without data
  is visible in the logs immediately rather than on the first search query.

Refreshing content in production = run the data workflow, then rebuild and
redeploy the app image as usual (no Helm/infra changes needed). A local
`docker build` without `WRI_INSIGHTS_S3_URI`/creds skips the pull and relies on
the bind-mounted `./data` at runtime instead.
