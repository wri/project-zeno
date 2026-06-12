# WRI Insights corpus + sgrep index snapshot, published by the
# wri-insights-data workflow (.github/workflows/wri-insights-data.yml).
ARG WRI_INSIGHTS_DATA_IMAGE=public.ecr.aws/b7u8b0a6/project-zeno/wri-insights-data:latest
FROM ${WRI_INSIGHTS_DATA_IMAGE} AS wri-insights-data

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
ADD ./db /app/db
COPY --from=wri-insights-data /data /app/data

WORKDIR /app

# Install only the main dependencies - no dev deps
RUN uv sync --frozen --no-dev

# Bake the sgrep embedding model into the image so pods never need Hugging
# Face network access, then verify the data snapshot is usable so a broken
# image fails at build time rather than on the first search query.
ENV HF_HOME=/app/.hf-cache
RUN uv run --no-sync python -c "\
import sys; \
from src.agent.utils.sgrep import data_status, get_model; \
get_model(); \
ok, detail = data_status(min_articles=2000); \
print(detail); \
sys.exit(0 if ok else 1)"
