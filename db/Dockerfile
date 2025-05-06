FROM python:3.11-slim

WORKDIR /app/db

# Install Alembic
RUN pip install --no-cache-dir alembic psycopg2-binary pydantic

# Copy migration scripts and models
COPY . /app/db

RUN chmod +x /app/db/init-multiple-dbs.sh && \
    chmod +x /app/db/entrypoint.sh

# Default command (can be overridden)
CMD ["./entrypoint.sh"]
