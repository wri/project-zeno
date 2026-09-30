# Ephemeral environments (ECS Fargate)

Ephemeral deployments of a specific commit. Each gets its own ECS service and
its own database instance; the load balancer, cluster and bastion are shared.

```
terraform/          shared and long-lived: load balancer, cluster, bastion,
                    IAM, secrets
terraform/env/      one workspace per commit: database, service, target group,
                    listener
```

Split so that destroying a deployment cannot take the shared infrastructure with
it. The env stack finds shared resources by name (`var.shared_prefix`).

Day to day, use the **Ephemeral Environment** workflow rather than running Terraform
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
    --name "/horizon-ephemeral/$name" --value "..."
done
```

`DATABASE_URL` is built by Terraform, since it
depends on the RDS endpoint.

### 2. Shared stack

```bash
cd terraform
terraform init -backend-config=vars/backend-shared.tfvars
terraform apply
```

### 3. Reference snapshot

Deployments restore their database from a snapshot holding the reference data.
Set its id as the `EPHEMERAL_SEED_SNAPSHOT_ID` repository variable. See
**`docs/deployment-database.md`** for rebuilding it.

## Notes

- Each deployment restores its own database instance from the snapshot, then
  migrates it. Commits older than the snapshot cannot run; rebuild it to move
  that floor.
- **Every deployment is a real RDS instance**, roughly $1.50/day. Destroy the ones
  you're finished with; `docs/deployment-database.md` has a query for finding
  orphans. A scheduled sweep would be a sensible addition.
- Databases are private; reach one through the bastion via SSM port forwarding.
  Requires the Session Manager plugin locally.
- Set `desired_count = 0` to park a deployment without destroying it.
- **Encryption at rest is off**, inherited from the snapshot. To enable it, copy
  the snapshot with a KMS key (`aws rds copy-db-snapshot --kms-key-id <key>`) and
  point `EPHEMERAL_SEED_SNAPSHOT_ID` at the copy.
