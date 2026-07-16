FROM python:3.12.8-slim-bookworm

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install system dependencies including PostgreSQL development libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    libpq-dev \
    ca-certificates \
    libexpat1 \
    && rm -rf /var/lib/apt/lists/*

ADD https://astral.sh/uv/0.8.12/install.sh /uv-installer.sh

# Run the installer then remove it
RUN sh /uv-installer.sh && rm /uv-installer.sh

# Ensure the installed binary is on the `PATH`
ENV PATH="/root/.local/bin/:$PATH"

## Copy the project into the image
ADD ./pyproject.toml ./uv.lock ./README.md /app/
ADD ./src /app/src
ADD ./scripts /app/scripts
ADD ./db /app/db

WORKDIR /app

# Install only the main dependencies - no dev deps
RUN uv sync --frozen --no-dev

# Pull the insights blog corpus + sgrep index snapshot from S3, published by
# the ingest-blog-data workflow (.github/workflows/ingest-blog-data.yml). The
# snapshot downloads + extracts into /app/data. AWS creds are passed as build
# secrets (kept out of image layers); when no S3 URI/creds are supplied (local
# builds) the pull is a no-op and the bind-mounted ./data supplies the corpus.
ARG WRI_INSIGHTS_S3_URI
ARG AWS_DEFAULT_REGION=us-east-1
RUN --mount=type=secret,id=aws_access_key_id \
    --mount=type=secret,id=aws_secret_access_key \
    AWS_ACCESS_KEY_ID="$(cat /run/secrets/aws_access_key_id 2>/dev/null)" \
    AWS_SECRET_ACCESS_KEY="$(cat /run/secrets/aws_secret_access_key 2>/dev/null)" \
    uv run --no-sync python scripts/wri_insights_snapshot.py pull

# Bake the sgrep embedding model into the image so pods never need Hugging
# Face network access, then verify the data snapshot is usable so a broken
# image fails at build time rather than on the first search query. The data
# check is enforced only when a snapshot was pulled (WRI_INSIGHTS_S3_URI set);
# local builds without it rely on the bind-mounted ./data at runtime.
#
# build_index() bundles its own copy of the model into
# data/insights_index/model/ (see sgrep.py), which travels with the
# wri-insights S3 snapshot pulled above -- so _index_model() below normally
# loads it from disk and never touches the Hugging Face Hub. Local builds
# without a pulled snapshot (and any snapshot predating the bundled model)
# fall back to the Hub, so a short retry stays as a safety net for that path.
ENV HF_HOME=/app/.hf-cache
RUN for i in 1 2 3; do \
    uv run --no-sync python -c "\
import os, sys; \
from src.agent.utils.sgrep import DEFAULT_INDEX_DIR, _index_model, data_status; \
_index_model(DEFAULT_INDEX_DIR); \
ok, detail = data_status(min_articles=2000); \
print(detail); \
sys.exit(0)" && exit 0; \
    echo "Embedding model check failed (attempt $i/3), retrying in 15s..." >&2; \
    sleep 15; \
    done; \
    exit 1
