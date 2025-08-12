#!/bin/bash
set -e

# Wait for database to be ready
until python -c "
import psycopg
import os
import sys

print('Attempting to connect to database with:')
print(f'Host: {os.environ[\"PGHOST\"]}')
print(f'Port: {os.environ[\"PGPORT\"]}')
print(f'User: {os.environ[\"PGUSER\"]}')
print(f'Database: {os.environ[\"PGDATABASE\"]}')

try:
    conn = psycopg.connect(
        host=os.environ['PGHOST'],
        port=os.environ['PGPORT'],
        user=os.environ['PGUSER'],
        password=os.environ['PGPASSWORD'],
        dbname=os.environ['PGDATABASE']
    )
    print('Successfully connected to database!')
    conn.close()
    exit(0)
except Exception as e:
    print(f'Connection failed with error: {str(e)}', file=sys.stderr)
    exit(1)
"; do
  echo "Postgres is unavailable - sleeping"
  sleep 1
done

echo "Postgres is up - executing dataset ingestion"

# Run dataset ingestion scripts
python -m datasets.natural_lands
python -m datasets.dist_alerts

# Print available collections
python -c "
import psycopg
import os
conn = psycopg.connect(
    host=os.environ['PGHOST'],
    port=os.environ['PGPORT'],
    user=os.environ['PGUSER'],
    password=os.environ['PGPASSWORD'],
    dbname=os.environ['PGDATABASE']
)
cursor = conn.cursor()
cursor.execute('SELECT * FROM collections;')
print(cursor.fetchall())
cursor.close()
conn.close()
"

# Keep container running
tail -f /dev/null
