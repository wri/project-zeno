FROM python:3.12-slim-bookworm

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# The installer requires curl (and certificates) to download the release archive
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates libexpat1 \
    && rm -rf /var/lib/apt/lists/*

RUN apt-get update && apt-get install -y build-essential libgdal-dev

ADD https://astral.sh/uv/0.5.4/install.sh /uv-installer.sh

# Run the installer then remove it
RUN sh /uv-installer.sh && rm /uv-installer.sh

# Ensure the installed binary is on the `PATH`
ENV PATH="/root/.local/bin/:$PATH"

# Copy the project into the image
ADD . /app

COPY ./ee-zeno-service-account.json /app/ee-zeno-service-account.json

# Sync the project into a new environment, using the frozen lockfile
WORKDIR /app

# Install the dependencies
RUN uv sync --frozen

# Command to run the application.
CMD ["uv", "run", "uvicorn", "api:app", "--reload", "--host", "0.0.0.0"]
