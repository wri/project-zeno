# Evals environment (ECS Fargate)

An isolated environment for running evals against a specific `project-zeno`
commit. Runs the API and its database only — no frontend, no eoAPI.

Day to day, deploy with the **Deploy Evals Environment** workflow, which takes a
commit SHA. Everything below is first-time setup.

## Layout

Environments are Terraform workspaces, so a second one is just a new workspace.

```bash
cd terraform
terraform init -backend-config=vars/backend-evals.tfvars
terraform workspace select -or-create=true evals
```

## First-time setup

### 1. Secrets

Write these once. Terraform reads them by ARN, so the values never enter state.

```bash
for name in GOOGLE_API_KEY ANTHROPIC_API_KEY WRI_BEARER_TOKEN \
            LANGFUSE_PUBLIC_KEY LANGFUSE_SECRET_KEY; do
  aws ssm put-parameter --type SecureString \
    --name "/zeno/evals/$name" --value "..."
done
```

`DATABASE_URL` is built and stored by this stack, since it depends on the RDS
endpoint.

### 2. Seed the database

The API serves areas from the `aois` table, which migrations create empty.
Filling it means ingesting GADM, WDPA, KBA and LandMark and then running
`build-aois` — hours of work and ~20GB of downloads.

That runs **once**. Afterwards every environment restores the resulting snapshot
in minutes.

```bash
# a. bring the stack up with no snapshot -> empty database
terraform apply -var db_password=<pw>

# b. ingest, one step per task (hours; each streams to CloudWatch)
scripts/run_seed_task.sh gadm
scripts/run_seed_task.sh wdpa
scripts/run_seed_task.sh kba
scripts/run_seed_task.sh landmark
scripts/run_seed_task.sh build-aois

# c. snapshot it (an RDS API call, so this one runs locally)
SEED_DB_INSTANCE=$(terraform output -raw db_instance_identifier) \
  scripts/build_seed_db.sh snapshot

# d. pin the snapshot it printed
terraform apply -var db_password=<pw> -var seed_snapshot_id=zeno-aoi-seed-YYYYMMDD
```

Set that snapshot id as the `EVALS_SEED_SNAPSHOT_ID` repository variable so
deploys pick it up. Repeat only when the source data vintage changes.

Ingest runs as a one-off ECS task rather than from a laptop because the data path
matters: through the bastion tunnel every row crosses SSM, which is far slower
than S3 -> Fargate -> RDS entirely inside AWS.

## Connecting to the database

For ad-hoc `psql` — debugging a failing eval, checking AOI counts — port-forward
through the bastion:

```bash
aws ssm start-session --target $(terraform output -raw bastion_instance_id) \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters host=$(terraform output -raw db_address),portNumber=5432,localPortNumber=5432
```

Then connect to `localhost:5432`. Fine for queries; too slow for bulk loading.

## Notes

- The API is reached at the raw ALB hostname over HTTP; there is no DNS record.
  `terraform output api_base_url` prints it.
- The database is private. The bastion is the way in, via SSM port forwarding —
  it has no inbound rules and no SSH key, so access is authorized by IAM alone.
  Requires the Session Manager plugin installed locally.
- Migrations run on every deploy: the api container runs `/app/db/migrate.sh`
  before starting uvicorn, so a restored snapshot is brought up to the deployed
  commit's revision automatically.
- Set `desired_count = 0` to park the environment between runs. The ALB and RDS
  still cost money; the Fargate task does not.
- If a migration ever reshapes the AOI tables, re-run `build-aois` against the
  restored database. It is idempotent, and the snapshot keeps the source tables
  it needs.
