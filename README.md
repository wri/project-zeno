# Project Zeno

Language Interface for Maps & WRI/LCL data APIs.

## Dependencies
- uv: https://docs.astral.sh/uv/getting-started/installation/
- ollama: https://ollama.com/
- postgresql: https://www.postgresql.org/ (for using local DB instead of docker)
- docker: https://docs.docker.com/

## Getting Started

1. Clone the repository: `git clone git@github.com:wri/project-zeno.git'
2. Navigate into the project directory: `cd project-zeno`
3. Install dependencies: `uv sync`
4. Activate the virtual environment: `source .venv/bin/activate`
5. Create your environment file: `cp .env.example .env`. Then, open `.env` and update the placeholder values with your actual credentials and configurations.
6. Obtain the `data/` directory contents: This step requires fetching data from the team (e.g., from a shared drive or internal source) and placing it into the `data/` folder in your local project.

For step 6, use the following command to download the required files into
the local `data/` directory

```bash
aws s3 sync s3://zeno-static-data/unified-agent-data/ data/
```


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
uv run streamlit run frontend/app.py
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

## Configure localhost Langfuse

1. `docker compose up langfuse-server` (or just spin up the whole backend with `docker compose up`)
2. Open your browser and navigate to http://localhost:3000 to create a Langfuse account.
3. Within the Langfuse UI, create an organization and then a project.
4. Copy the API keys (public and secret) generated for your project.
5. Update the `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` environment variables in your `docker-compose.yml` file with the copied keys.
