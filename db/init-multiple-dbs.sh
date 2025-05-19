#!/bin/bash
set -e

# Set password for psql
export PGPASSWORD="${POSTGRES_PASSWORD}"

# Define effective database names with defaults
APP_DB_EFFECTIVE="${APP_DB:-zeno-data}"
LANGFUSE_DB_EFFECTIVE="${LANGFUSE_DB:-langfuse}"

# Create additional databases if they do not exist
psql -h "${POSTGRES_HOST}" -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" \
    -v app_db_name="$APP_DB_EFFECTIVE" \
    -v langfuse_db_name="$LANGFUSE_DB_EFFECTIVE" <<-EOSQL
    SELECT 'CREATE DATABASE "' || :'app_db_name' || '"'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'app_db_name')\gexec

    SELECT 'CREATE DATABASE "' || :'langfuse_db_name' || '"'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'langfuse_db_name')\gexec
EOSQL
