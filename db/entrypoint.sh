#!/bin/bash
export DATABASE_URL="postgresql+psycopg2://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:5432/${APP_DB}"
./init-multiple-dbs.sh && \
alembic upgrade head
