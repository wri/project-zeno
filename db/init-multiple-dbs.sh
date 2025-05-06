#!/bin/bash
set -e

# Set password for psql
export PGPASSWORD="${POSTGRES_PASSWORD}"

# Create additional databases if they do not exist
psql -h "${POSTGRES_HOST}" -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
    CREATE DATABASE "${APP_DB:-zeno-data}";
    CREATE DATABASE "${LANGFUSE_DB:-langfuse}";
EOSQL
