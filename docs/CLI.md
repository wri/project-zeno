# CLI User Management Commands

This document describes the user management commands available in the Project Zeno CLI tool.

## Prerequisites

To run these commands, you need access to the Kubernetes cluster where Zeno is deployed. You'll execute the commands inside a running API pod.

## Command Execution

To run CLI commands, first get access to a running API pod:

```bash
kubectl exec $(kubectl get pods --no-headers | grep zeno-api | awk '{print $1}' | head -1) -- uv run python src/api/cli.py <command>
```

## Available Commands

### make-user-admin

Makes an existing user an administrator by updating their user type to admin.

**Usage:**
```bash
kubectl exec $(kubectl get pods --no-headers | grep zeno-api | awk '{print $1}' | head -1) -- uv run python src/api/cli.py make-user-admin --email admin@example.com
```

**Parameters:**
- `--email` (required): Email address of the user to make admin

**Output:**
```
✅ Made user admin:
   ID: user_123abc
   Name: John Doe
   Email: john.doe@company.com
   User Type: admin
   Updated: 2024-09-15 10:30:45
```

**Notes:**
- The user must already exist in the system
- This command changes their user type from regular user to admin
- Admin users have higher prompt quotas

### Machine users & API keys (scopes)

Machine users are accounts for programmatic (machine-to-machine) access. They
authenticate with an API key passed as a bearer token:
`Authorization: Bearer zeno-key:<prefix>:<secret>`.

Authorization is granted per-key via **scopes** (independent of `user_type`). An
endpoint that requires a scope is accessible to a superuser human, or to a machine
key that carries that scope. Currently defined scopes:

- `traces:read` — read access to the traces API (`/api/traces/*`).

**Create a machine user with a scoped key:**
```bash
kubectl exec $(kubectl get pods --no-headers | grep zeno-api | awk '{print $1}' | head -1) -- \
  uv run python src/api/cli.py create-machine-user \
  --name "Traces Reader" --email "traces-reader@example.com" \
  --create-key --key-name "traces" --scope traces:read
```

**Add a key (with one or more scopes) to an existing machine user:**
```bash
kubectl exec $(kubectl get pods --no-headers | grep zeno-api | awk '{print $1}' | head -1) -- \
  uv run python src/api/cli.py create-api-key \
  --user-id "machine_xxx" --key-name "traces" --scope traces:read
```

**Parameters:**
- `--scope` (repeatable): authorization scope(s) to grant the key. Unknown scopes
  are rejected. Defaults to none (a key with no scopes cannot reach scoped
  endpoints).

The token is printed once at creation — save it then; it is not recoverable.
`list-api-keys --user-id <id>` shows each key's scopes. Rotate/revoke with
`rotate-key` / `revoke-key`.

### ingest-langfuse-traces

Ingests Langfuse traces into Postgres (`langfuse_traces`) with an idempotent
upsert, recording a watermark per run so subsequent runs resume incrementally.

**Usage:**
```bash
# Default: resume from the last watermark (or last 24h on first run)
kubectl exec $(kubectl get pods --no-headers | grep zeno-api | awk '{print $1}' | head -1) -- \
  uv run python src/api/cli.py ingest-langfuse-traces

# Historical backfill over an explicit window
kubectl exec $(kubectl get pods --no-headers | grep zeno-api | awk '{print $1}' | head -1) -- \
  uv run python src/api/cli.py ingest-langfuse-traces --backfill --since 2025-12-22T00:00:00Z
```

**Parameters:**
- `--since` (ISO datetime): start of the window; overrides the watermark. Required with `--backfill`.
- `--until` (ISO datetime): end of the window (default: now).
- `--backfill`: historical backfill from `--since`.
- `--environment` (repeatable): filter to specific environment(s) (default: all).
- `--overlap-hours` (default 12): re-scan overlap before the watermark to catch delayed traces.
- `--chunk-hours` (default 24): window chunk size.
- `--batch-size` (default 300): fetch page / upsert batch size.
- `--dry-run`: fetch + parse but do not write (connectivity/parse smoke test).

**Notes:**
- Requires `LANGFUSE_HOST`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and `DATABASE_URL` in the pod environment.
- Each run prints a summary line: `fetched=… upserted=… chunks=… failed=… status=… watermark=…`.
- The watermark only advances on fully-completed chunks, so an interrupted run is safe to re-run.
- Token counts come from each trace's generation observations, fetched once per window
  alongside the traces. That is what makes `turn_tokens` cover the LLM calls made inside
  tools, and it is what splits spend into `agent_*` and `tool_*`. If that fetch fails the
  window still ingests, on agent-level usage only — watch the `agent_tokens` fill rate in
  `langfuse_ingestion_runs` for that.
- Traces tagged `auxiliary` are skipped. Those are single LLM calls made outside a turn
  (thread naming, area naming, language detection); they carry no `AgentState`, so
  ingesting them would add zero-token `EMPTY` rows and drag every per-turn average down.
  Their cost stays visible in Langfuse under the thread's session id.
- **Parser v3 changed what `turn_tokens` means**: it now covers every LLM call in the
  turn, not just the agent's own. Re-run with `--backfill --since` over the window you
  analyse to put existing rows on the new basis, or the series has a step in it where
  the parser version changes.

### backfill-turn-fields

Backfills the turn-analytics columns (`turn_index`, `is_final_turn_in_thread`,
`insight_created_this_turn`, `datasets_analysed_this_turn`) for rows that predate the
feature. The migrations add these columns **empty** — this command populates them
out-of-band, keeping the data pass out of the blocking deploy migration. **Run it once
after deploying the turn-analytics migrations.** New rows are set automatically during
ingest, so this is a one-time catch-up; it's idempotent and safe to re-run (writes
nothing the second time).

**Usage:**
```bash
# Preview how many rows would change
kubectl exec $(kubectl get pods --no-headers | grep zeno-api | awk '{print $1}' | head -1) -- \
  uv run python src/api/cli.py backfill-turn-fields --dry-run

# Run the backfill
kubectl exec $(kubectl get pods --no-headers | grep zeno-api | awk '{print $1}' | head -1) -- \
  uv run python src/api/cli.py backfill-turn-fields
```

**Parameters:**
- `--batch-size` (default 500): sessions renumbered per committed batch (bounds the transaction).
- `--dry-run`: report how many rows would change without writing.

**Notes:**
- Requires `DATABASE_URL` in the pod environment.
- Until it runs, pre-existing rows report NULL turn fields — the API tolerates this
  (analytics is just incomplete for those rows), so there's no rush within a deploy.

### langfuse-model-prices

Reports which models Langfuse fails to price. Langfuse works out cost by matching an
observation's model name against its model-definition table. A model it does not
recognise — a preview name, or one newly configured in `MODEL` / `SMALL_MODEL` /
`CODING_MODEL` — is stored with usage but **zero cost**, so cost-per-query understates
by that model's entire share with nothing in the data to show it. Run this after any
model change.

**Usage:**
```bash
# Which models did the last 24h use, and are they all priced?
kubectl exec $(kubectl get pods --no-headers | grep zeno-api | awk '{print $1}' | head -1) -- \
  uv run python src/api/cli.py langfuse-model-prices

# One environment, longer look-back
kubectl exec $(kubectl get pods --no-headers | grep zeno-api | awk '{print $1}' | head -1) -- \
  uv run python src/api/cli.py langfuse-model-prices --hours 168 --environment production
```

**Parameters:**
- `--hours` (default 24): look-back window.
- `--environment`: filter to one environment. Default: all.

**Notes:**
- Requires `LANGFUSE_HOST`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`. It reads
  Langfuse only — no database, no writes.
- `UNPRICED` means the model produced tokens and no cost. `PARTIAL` means only some
  calls were priced, which usually means the definition was added part-way through the
  window.
- To fix an `UNPRICED` model: add a model definition with its prices in Langfuse
  (Settings → Models), then re-run `ingest-langfuse-traces --backfill --since` over the
  affected window so the stored costs are recomputed.

### build-aois

Populates the unified `aois` / `user_aois` tables from data already loaded in the
database: the reference tables (`geometries_gadm`, `geometries_kba`,
`geometries_wdpa`, `geometries_landmark`) and `custom_areas`. **The API reads
`aois`, so this is a precondition, not an optional extra.** It is an in-database,
set-based transform — no rows travel through Python. It is idempotent and safe to
re-run. Run it out of band, never in the blocking migrate Job: the reference build
is heavy and would hold up the deploy.

**Usage:**
```bash
# Size up the reference geometry before a real run (no writes)
kubectl exec $(kubectl get pods --no-headers | grep zeno-api | awk '{print $1}' | head -1) -- \
  uv run python src/api/cli.py build-aois --inspect

# Report counts, then roll everything back
kubectl exec $(kubectl get pods --no-headers | grep zeno-api | awk '{print $1}' | head -1) -- \
  uv run python src/api/cli.py build-aois --dry-run

# Full build
kubectl exec $(kubectl get pods --no-headers | grep zeno-api | awk '{print $1}' | head -1) -- \
  uv run python src/api/cli.py build-aois

# Custom areas only, removing rows whose custom area is gone
kubectl exec $(kubectl get pods --no-headers | grep zeno-api | awk '{print $1}' | head -1) -- \
  uv run python src/api/cli.py build-aois --source custom --prune --dry-run
```

**Parameters:**
- `--source` (repeatable, default all): limit to `gadm`, `kba`, `wdpa`, `landmark`
  and/or `custom`. A source whose table is absent is skipped with a message, so
  `--source custom` works on a database that has no `geometries_*` tables.
- `--dry-run`: run the transform in a transaction, report counts, then roll back.
- `--chunks` (default 16): hash-partitioned passes per reference source. Each is its
  own statement and transaction, so higher means lower peak memory and more scans.
- `--inspect`: don't build; print per-source geometry statistics (vertex
  distribution, types). Skips `custom`, whose geometry is a GeoJSON-string list.
- `--prune`: **custom only.** Also delete the mirrored `aois` rows that have no
  `custom_areas` row. Off by default, because a wrong or empty `custom_areas` table
  makes every mirrored row look like an orphan. Rejected with `--inspect`, or when
  `--source` excludes `custom`.

**Notes:**
- Requires `DATABASE_URL` in the pod environment.
- Each source commits independently, and reference sources commit per chunk, so a
  late failure never discards completed work — re-run to resume. The command prints
  which sources committed before a failure.
- It runs `ANALYZE` on both tables at the end. A bulk insert leaves the planner
  without statistics until autoanalyze fires, and until then it ignores the indexes
  on `aois`. Skipped under `--dry-run`.
- **Ordering for the deploy that first points the API at `aois`:** the reference
  sources never change, so one build serves them. `custom_areas` does change, and
  the write-through mirror that keeps `aois` current ships with that API change.
  Any custom area created, renamed or deleted between the previous build and that
  deploy has drifted. So deploy first, **then** run `build-aois --source custom
  --prune`. Running it before the deploy leaves a fresh gap between the run and the
  pods going live. Afterwards the write-through keeps the mirror correct and this
  catch-up is not needed again.

## Error Handling

The command includes error handling:

- **make-user-admin**: Returns an error if the user with the specified email doesn't exist
- **create-api-key / create-machine-user**: Returns an error if an unknown `--scope` is supplied
- **build-aois**: Returns a usage error if `--prune` is combined with `--inspect`, or
  with a `--source` set that excludes `custom`
