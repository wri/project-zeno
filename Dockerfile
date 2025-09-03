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
ADD ./client.py /app/src/frontend/client.py

WORKDIR /app

# Install only the main dependencies - no dev deps
RUN uv sync --frozen --no-dev
