# Global Nature Watch Agent

Language Interface for Maps & WRI/LCL data APIs.

## Project overview

The core of this project is an LLM powered agent that drives
the conversations for Global Nature Watch. The project is fully
open source and can be run locally with the appropriate keys
for accessing external services.

### Agent

Our agent is a simple ReAct agent implemented in Langgraph. It
uses tools. The tools at a high level do the following things

- Provide information about its capabilities
- Retrieve areas of interest
- Select appropriate datasets
- Retrieve statistics from the WRI analytics api
- Generate insights including charts from the data

The LLM to use is plug and play, we rely mostly on Sonnet & Gemini
for planning and tool calling.

For detailed technical architecture, see [Agent Architecture Documentation](docs/AGENT_ARCHITECTURE.md).

### Infrastructure

To enable that, the project relies on a set of services being deployed with it.

- eoAPI to provide access to the LCL data in a STAC catalog and serving tiles
- Langfuse for tracing of the agent interactions
- PostgreSQL for the API data and geographic search of AOIs
- FastAPI deployment for the API

All these services are being managed and deployed throug our deploy
repository at [project-zeno-deploy](https://github.com/wri/project-zeno-deploy)

### Frontend

The frontend application for this project is a nextjs project
that can be found at [project-zeno-next](https://github.com/wri/project-zeno-next)

### Evals

We have an evaluation framework we use to do end-to-end testing of the
agent on the deployed API. The framework can be found in the [gnw-evals](https://github.com/wri/gnw-evals) repository.

### STAC

We have a set of scripts to ingest STAC data into the eoAPI deployment. The ingestion code
for STAC can be found in the [gnw-stac](https://github.com/wri/gnw-stac) repository.

## Dependencies

- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- [postgresql](https://www.postgresql.org/) (for using local DB instead of docker)
- [docker](https://docs.docker.com/)

## Local Development Setup

We use uv for package management and docker-compose
for running the system locally.

1. **Clone and setup:**

   ```bash
   git clone git@github.com:wri/project-zeno.git
   cd project-zeno
   uv sync
   source .venv/bin/activate
   ```

2. **Environment configuration:**

   ```bash
   cp .env.example .env
   # Edit .env with your API keys and credentials
   ```

3. **Build dataset RAG database:**

   Our agent uses a RAG database to select datasets. The RAG database
   can be built locally using

   ```bash
   uv run python src/ingest/embed_datasets.py
   ```

   As an alternative, the current production table can also be
   retrieved from S3 if you have the corresponding access permissions.

   ```bash
   aws s3 sync s3://zeno-static-data/ data/
   ```

4. **Start infrastructure services:**

   ```bash
   make up       # Start Docker services (PostgreSQL, test DB, migrations via docker-compose.dev.yaml)
   ```

5. **Ingest data (required after starting database):**

   After starting the database and infrastructure services, you need to ingest the required datasets. Feel free to run all or just the ones you need.

   This downloads ~2 GB of data per dataset except for WDPA which is ~10 GB. It's ok to skip WDPA if you don't need it.

   Make sure you're set up with WRI AWS credentials in your `.env` file to access the S3 bucket.

   ```bash
   uv run python src/ingest/ingest_gadm.py
   uv run python src/ingest/ingest_kba.py
   uv run python src/ingest/ingest_landmark.py
   uv run python src/ingest/ingest_wdpa.py
   ```

   See `src/ingest/` directory for details on each ingestion script.

6. **Start application services:**

   ```bash
   make api      # Run API locally (port 8000)
   make frontend # Run Streamlit frontend (port 8501)
   ```

   Or start everything at once (after data ingestion):

   ```bash
   make dev      # Starts API + frontend (requires infrastructure already running)
   ```

7. **Setup Local Langfuse:**
   a. Clone the Langfuse repository outside your current project directory

   ```bash
   cd ..
   git clone https://github.com/langfuse/langfuse.git
   cd langfuse
   ```

   b. Start the Langfuse server

   ```bash
   docker compose up -d
   ```

   c. Access the Langfuse UI at <http://localhost:3000>
   1. Create an account
   2. Create a new project
   3. Copy the API keys from your project settings

   d. Return to your project directory and update your .env file

   ```bash
   cd ../project-zeno
   # Update these values in your .env file:
   LANGFUSE_HOST=http://localhost:3000
   LANGFUSE_PUBLIC_KEY=your_public_key_here
   LANGFUSE_SECRET_KEY=your_secret_key_here
   ```

   To disable locally, use following flag

   ```bash
   LANGFUSE_TRACING_ENABLED=true
   ```

8. **Access the application:**

   - Frontend: <http://localhost:8501>
   - API: <http://localhost:8000>
   - Langfuse: <http://localhost:3000>

## Development Commands

```bash
make help     # Show all available commands
make up       # Start Docker infrastructure
make down     # Stop Docker infrastructure
make api      # Run API with hot reload
make frontend # Run frontend with hot reload
make dev      # Start full development environment
```

## Testing

### API Tests

Running `make up` brings up a `zeno-data_test` database (in docker-compose.dev.yaml) used by pytest. Set `TEST_DATABASE_URL` in `.env` (e.g. `postgresql+asyncpg://postgres:postgres@localhost:5434/zeno-data_test` for the dev test container). You can also create the test database manually:

```bash
createuser -s postgres # if you don't have a postgres user
createdb -U postgres zeno-data_test
```

Then run the API tests using pytest:

```bash
uv run pytest tests/api/
```

## CLI User Management

For user administration commands (making users admin, whitelisting emails), see [CLI Documentation](docs/CLI.md).

## Environment Files

- `.env` - Base configuration (production settings)

The system automatically loads `.env`. To run only the frontend: `make frontend` or `uv run streamlit run frontend/app.py --server.port=8501`.

## Setup Database

1. Using docker (full stack; see `docker-compose.yaml`):

   ```bash
   docker compose up -d
   # Frontend runs in a container; for local-only frontend: make frontend
   ```

2. Using postgresql:

   a. Create a new database

   ```bash
   createuser -s postgres # if you don't have a postgres user
   createdb -U postgres zeno-data-local
   # Run migrations from the db directory (alembic reads DATABASE_URL from env; same URL as .env is fine)
   cd db && DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/zeno-data-local alembic upgrade head && cd ..

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
   DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/zeno-data-local
   ```

## Configure localhost Langfuse (full docker-compose)

When using the full stack (`docker compose up` with `docker-compose.yaml`), Langfuse and ClickHouse are included. For local dev with `make up` only, use the separate Langfuse setup in step 7 above.

1. `docker compose up -d` (or run the `langfuse-web` service)
2. Open <http://localhost:3000> and create a Langfuse account.
3. In the Langfuse UI, create an organization and a project.
4. Copy the project API keys (public and secret).
5. Set `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` in your `.env` (or in `docker-compose.yaml` if you rely on env there).
