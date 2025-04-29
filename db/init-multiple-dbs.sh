#!/bin/bash
set -e

# Create additional databases if they do not exist
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
    CREATE DATABASE "${APP_DB:-zeno-data}";
    CREATE DATABASE "${LANGFUSE_DB:-langfuse}";
EOSQL
