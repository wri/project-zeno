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

## Error Handling

The command includes error handling:

- **make-user-admin**: Returns an error if the user with the specified email doesn't exist
- **create-api-key / create-machine-user**: Returns an error if an unknown `--scope` is supplied
