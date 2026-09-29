#!/usr/bin/env bash
#
# Build the AOI seed database and snapshot it.
#
# The unified `aois` table that the API reads is created EMPTY by migration
# ceea2a027738; it is populated out of band by the `build-aois` CLI, which in
# turn reads the `geometries_*` tables written by src/ingest/*.py. This script
# runs that whole chain once and takes an RDS snapshot of the result, so that
# evals environments can restore the snapshot instead of re-ingesting (hours,
# ~20GB of downloads).
#
# Run it by hand against the database Terraform created. This script never
# creates infrastructure: bring the stack up with no seed_snapshot_id (which
# gives an empty database), plus db_publicly_accessible=true and
# db_allowed_cidrs=["<your-ip>/32"] so it is reachable from here. See
# terraform/README.md.
#
# Usage:
#   DATABASE_URL=postgresql+asyncpg://postgres:<pw>@$(terraform output -raw db_address)/ \
#   SEED_DB_INSTANCE=$(terraform output -raw db_instance_identifier) \
#     scripts/build_seed_db.sh [step ...]
#
# With no arguments every step runs in order. Naming steps runs only those,
# which is how you resume after a failure:
#
#   scripts/build_seed_db.sh landmark build-aois snapshot
#
# Steps are individually safe to re-run: the ingests use if_exists="replace"
# and build-aois is idempotent.
#
# Needs ~30GB of free disk (downloads cache in /tmp) and AWS credentials with
# read access to the requester-pays buckets gfw-data-lake and ndjson-layers --
# those reads are billed to whoever runs this.

set -euo pipefail

ALL_STEPS=(migrate gadm wdpa kba landmark build-aois snapshot)

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

log() {
  printf '\n=== %s ===\n' "$1" >&2
}

# Only the database steps need a connection; `snapshot` is an RDS API call.
require_database_url() {
  : "${DATABASE_URL:?set DATABASE_URL to the seed database, e.g. postgresql+asyncpg://user:pass@host/}"
  export DATABASE_URL
}

run_step() {
  case "$1" in
    migrate)
      require_database_url
      log "alembic upgrade head"
      (cd db && uv run alembic upgrade head)
      ;;
    gadm|wdpa|kba|landmark)
      require_database_url
      log "ingest $1"
      uv run python "src/ingest/ingest_$1.py"
      ;;
    build-aois)
      require_database_url
      log "build-aois"
      uv run python src/api/cli.py build-aois
      ;;
    snapshot)
      : "${SEED_DB_INSTANCE:?set SEED_DB_INSTANCE to the RDS instance identifier to snapshot}"
      snapshot_id="${SEED_SNAPSHOT_ID:-zeno-aoi-seed-$(date -u +%Y%m%d)}"
      log "snapshot $SEED_DB_INSTANCE -> $snapshot_id"
      aws rds create-db-snapshot \
        --db-instance-identifier "$SEED_DB_INSTANCE" \
        --db-snapshot-identifier "$snapshot_id"
      aws rds wait db-snapshot-available \
        --db-snapshot-identifier "$snapshot_id"
      printf '\nSnapshot ready. Deploy with:\n  -var seed_snapshot_id=%s\n' "$snapshot_id" >&2
      ;;
    *)
      printf 'unknown step: %s\nvalid steps: %s\n' "$1" "${ALL_STEPS[*]}" >&2
      exit 64
      ;;
  esac
}

steps=("$@")
if [ ${#steps[@]} -eq 0 ]; then
  steps=("${ALL_STEPS[@]}")
fi

# Reject unknown steps up front rather than failing halfway through an ingest.
for step in "${steps[@]}"; do
  case " ${ALL_STEPS[*]} " in
    *" $step "*) ;;
    *)
      printf 'unknown step: %s\nvalid steps: %s\n' "$step" "${ALL_STEPS[*]}" >&2
      exit 64
      ;;
  esac
done

for step in "${steps[@]}"; do
  run_step "$step"
done

log "done: ${steps[*]}"
