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

## Generate global overviews

Some of the collections to be ingested will be tiled. These will be
harder to visualize at low zoom levels, because many separate files
have to be touched.

For this reason, we extract the overviews from the COG tiles and stitch
them together into a global overview layer for lower zoom levels.

The `generate_global_overview.py` file can be used to create that global
overview file. COGs can not be generated incrementally. So after creating
the merged overview file, use the gdal commandline to covert it into a COG.

```bash
gdalwarp -of COG natural_lands_mosaic_overview_merged.tif natural_lands_mosaic_overview_cog.tif
```

## Tool for creating zonal stats

We also developed a tool that could be used by the agents to obtain
zonal stats for the DIST alerts layer. This is an example that we
might not use in zeno. But its added here for reference and if we
need it in the future. The tool is in the
[zonal_stats_dist.py](zonal_stats_dist.py) file.
