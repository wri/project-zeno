#!/bin/bash
set -e

# Set password for psql
export PGPASSWORD="${POSTGRES_PASSWORD}"

# Create additional databases if they do not exist
psql -h "${POSTGRES_HOST}" -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_database WHERE datname = '${APP_DB:-zeno-data}') THEN
            CREATE DATABASE "${APP_DB:-zeno-data}";
        END IF;
        IF NOT EXISTS (SELECT FROM pg_database WHERE datname = '${LANGFUSE_DB:-langfuse}') THEN
            CREATE DATABASE "${LANGFUSE_DB:-langfuse}";
        END IF;
    END
    \$\$;
EOSQL
