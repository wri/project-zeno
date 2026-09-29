# Evals environments (ECS Fargate)

Ephemeral deployments of a specific commit. Each gets its own ECS service and
database; the database instance, load balancer, cluster and bastion are shared.

```
terraform/          shared and long-lived: database, load balancer, cluster,
                    bastion, IAM, secrets
terraform/env/      one workspace per commit: service, target group, listener
```

Split so that destroying a deployment cannot take the database with it. The env
stack finds shared resources by name (`var.shared_prefix`).

Day to day, use the **Evals Environment** workflow rather than running Terraform
directly; it takes a commit SHA and a create/destroy action.

## Reaching an environment

Deployments share one load balancer and are separated by port, derived from the
workspace name so it is stable across applies:

```
http://<shared-alb-dns>:<port>     # terraform -chdir=terraform/env output api_base_url
```

**HTTP, not HTTPS.** TLS needs either a domain we control or a CloudFront
distribution per deployment. Revisit if these stop being short-lived.

## First-time setup

### 1. Secrets

Written once, out of band. Terraform references them by ARN, so the values never
enter state.

```bash
for name in GOOGLE_API_KEY ANTHROPIC_API_KEY WRI_BEARER_TOKEN \
            LANGFUSE_PUBLIC_KEY LANGFUSE_SECRET_KEY; do
  aws ssm put-parameter --type SecureString \
    --name "/zeno/evals/$name" --value "..."
done
```

`DATABASE_URL` and `MAINTENANCE_DATABASE_URL` are built by Terraform, since they
depend on the RDS endpoint.

### 2. Shared stack

```bash
cd terraform
terraform init -backend-config=vars/backend-evals.tfvars
terraform apply -var db_password=<pw> -var seed_snapshot_id=zeno-aoi-seed-YYYYMMDD
```

`seed_snapshot_id` has no default: an empty value creates an empty instance,
which is right for a first bring-up and destructive on a replace.

### 3. Seed database and template

The API serves areas from a reference table that migrations create empty.
Filling it is hours of work and runs once; every deployment then clones the
result. See **`docs/deployment-database.md`**.

## Notes

- Each deployment clones its database from the template at startup, then
  migrates it. Commits older than the template cannot run; rebuild it to move
  that floor.
- Each database is a full copy of the template. Storage autoscales, but destroy
  deployments you're done with.
- The database is private; reach it through the bastion via SSM port forwarding.
  Requires the Session Manager plugin locally.
- Set `desired_count = 0` to park a deployment without destroying it.
- **Encryption at rest is off.** Enabling it replaces the instance, and an
  unencrypted snapshot must be copied with a KMS key first:
  `aws rds copy-db-snapshot --kms-key-id <key>`, then apply with
  `-var db_storage_encrypted=true -var seed_snapshot_id=<copy>`, then rebuild
  the template.
