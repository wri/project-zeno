#!/bin/sh
set -e
cd /app/db
# --no-sync: the image already installed dependencies without the dev group.
# Without it uv reconciles the environment on every start and reinstalls the
# dev packages, adding minutes to container startup.
exec uv run --no-sync alembic upgrade head
