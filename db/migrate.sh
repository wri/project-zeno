#!/bin/sh
set -e
cd /app/db
exec uv run alembic upgrade head
