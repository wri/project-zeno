# Project Zeno

Language Interface for Maps & WRI/LCL data APIs.

## Dependencies
- uv: https://docs.astral.sh/uv/getting-started/installation/
- ollama: https://ollama.com/
- postgresql: https://www.postgresql.org/

## Getting Started

1. Clone the repository: `git clone git@github.com:wri/project-zeno.git'
2. Change into the project directory: `cd project-zeno`
3. Install dependencies: `uv sync`
4. Activate the environment: `source .venv/bin/activate`
5. Run `cp .env.example .env` and replace values appropriately in the .env file

## Start the agent API

The following example shows how the streaming response can be obtained.

Run fastapi server

```bash
uv run uvicorn api:app --reload
```

Test the API

```python
import requests

msg = "How many users are using GFW and how long did it take to get there?"
response = requests.post("http://127.0.0.1:8000/stream", json=dict(query=msg), stream=True)
for line in response:
    if line:
        print(line.decode())
```

Run streamlit

```bash
uv run streamlit run frontend/app.py
```

## Setup Database

1. Using docker:

```bash
docker compose up -d
```

2. Using postgresql:

a. Create a new database

```bash
createuser -s postgres # if you don't have a postgres user
createdb -U postgres zeno-data-local
alembic upgrade head

# Check if you have the database running
psql zeno-data-local

# Check if you have the tables created
\dt

# Output
#               List of relations
#  Schema |      Name       | Type  |  Owner   
# --------+-----------------+-------+----------
#  public | alembic_version | table | postgres
#  public | threads         | table | postgres
#  public | users           | table | postgres
```

b. Add the database URL to the .env file:
```bash
DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/zeno-data-local
```