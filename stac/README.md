# STAC Ingestion for Zeno

## Installation

1. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

2. Set up environment variables in `env/.env_localhost`:

   ```bash
   PGHOST=localhost
   PGPORT=5432
   PGDATABASE=pgstac
   PGUSER=your_username
   PGPASSWORD=your_password
   AWS_ACCESS_KEY_ID="***"
   AWS_SECRET_ACCESS_KEY="***"
   ```

## Usage

### Running Locally

1. Ensure PostgreSQL with pgSTAC is running
2. Activate the virtual environment
3. Run the main script:

   ```bash
   python datasets/natural_lands.py
   python datasets/dist_alerts.py
   ```

### Running with Docker

Running docker compose will trigger the ingestion into
the dockerized STAC DB in the "ingestion" container through
the entryponit.sh script.

1. Build and start the containers:

   ```bash
   docker-compose up
   ```

### Running against remote

For ingestion into remote PGSTAC DB, set the env vars
to point to a remote database and run the python
scripts directly. The docker setup will not be necessary.

```bash
pip install -r requirements.txt
python datasets/natural_lands.py
python datasets/dist_alerts.py   
```
