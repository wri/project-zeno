#!/usr/bin/env python
"""
dump_basemaps_tables.py
---------------------
Export every table in a Basemaps database to its own Parquet file.
• Geometry columns are preserved; DuckDB writes valid GeoParquet metadata.
• Output directory is created automatically.
Usage:
    python dump_basemaps_tables.py path/to/basemaps.duckdb [-o exports]
"""
import duckdb
import argparse
from pathlib import Path

def main(db_path: str, outdir: str):
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(db_path)
    con.execute("INSTALL spatial; LOAD spatial;")          # Needed once

    # list only user‑visible tables in the default schema
    tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]

    for t in tables:
        outfile = outdir / f"{t}.parquet"
        con.execute(f"COPY {t} TO '{outfile}' (FORMAT PARQUET, COMPRESSION ZSTD);")
        print(f"✓ {t}  →  {outfile}")

    con.close()

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("db", help="Path to .duckdb database file")
    p.add_argument("-o", "--outdir", default="data/geocode/exports", help="Directory for Parquet files")
    args = p.parse_args()
    main(args.db, args.outdir)
