#!/usr/bin/env bash
#
# Run a seeding step as a one-off ECS task, inside the VPC.
#
# Same work as running scripts/build_seed_db.sh locally through the bastion, but
# without the SSM tunnel in the data path: reading GADM from your laptop is fine,
# pushing millions of geometries back up through the tunnel is not. Here both
# hops -- S3 to the task, task to RDS -- stay on AWS's network.
#
# Usage, from the repo root:
#   scripts/run_seed_task.sh gadm
#   scripts/run_seed_task.sh wdpa kba landmark
#   scripts/run_seed_task.sh build-aois
#
# One task per invocation, so each gets its own fresh 100GB of disk. Steps are
# individually safe to re-run. Tails CloudWatch until the task stops and exits
# with the container's exit code.
#
# The `snapshot` step is deliberately not supported here: it calls the RDS API
# rather than touching the database, so run it from your laptop instead --
#   SEED_DB_INSTANCE=$(terraform -chdir=terraform output -raw db_instance_identifier) \
#     scripts/build_seed_db.sh snapshot

set -euo pipefail

if [ $# -eq 0 ]; then
  echo "usage: $0 <step> [step ...]   (gadm wdpa kba landmark migrate build-aois)" >&2
  exit 64
fi

for step in "$@"; do
  case "$step" in
    migrate|gadm|wdpa|kba|landmark|build-aois) ;;
    snapshot)
      echo "run 'snapshot' locally, not as a task -- see the header of this script" >&2
      exit 64
      ;;
    *)
      echo "unknown step: $step" >&2
      exit 64
      ;;
  esac
done

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tf="$repo_root/terraform"
region="${AWS_REGION:-us-east-1}"

cluster=$(terraform -chdir="$tf" output -raw cluster_name)
task_def=$(terraform -chdir="$tf" output -raw seed_task_definition_arn)
subnets=$(terraform -chdir="$tf" output -json task_subnet_ids | jq -r 'join(",")')
sg=$(terraform -chdir="$tf" output -raw task_security_group_id)
log_group=$(terraform -chdir="$tf" output -raw seed_log_group)

# `sh -c` so the steps run in sequence inside one task, sharing its disk cache.
command_json=$(printf '%s\n' "$*" | jq -R '{
  containerOverrides: [{
    name: "seed",
    command: ["/bin/sh", "-c", ("scripts/build_seed_db.sh " + .)]
  }]
}')

echo "Starting seed task: $*" >&2

task_arn=$(aws ecs run-task \
  --region "$region" \
  --cluster "$cluster" \
  --task-definition "$task_def" \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$subnets],securityGroups=[$sg],assignPublicIp=ENABLED}" \
  --overrides "$command_json" \
  --query 'tasks[0].taskArn' --output text)

task_id="${task_arn##*/}"
echo "Task: $task_id" >&2
echo "Logs: $log_group/ecs/seed/$task_id" >&2
echo >&2

# Follow the logs until the task stops. `logs tail --follow` exits when the
# stream goes quiet, so poll the task state around it rather than trusting it.
aws logs tail "$log_group" --region "$region" --follow \
  --log-stream-names "ecs/seed/$task_id" --format short &
tail_pid=$!

aws ecs wait tasks-stopped --region "$region" --cluster "$cluster" --tasks "$task_arn"
sleep 5   # let the last lines flush
kill "$tail_pid" 2>/dev/null || true

exit_code=$(aws ecs describe-tasks --region "$region" --cluster "$cluster" --tasks "$task_arn" \
  --query 'tasks[0].containers[0].exitCode' --output text)
reason=$(aws ecs describe-tasks --region "$region" --cluster "$cluster" --tasks "$task_arn" \
  --query 'tasks[0].stoppedReason' --output text)

echo >&2
echo "Task $task_id stopped: exit=$exit_code reason=$reason" >&2
[ "$exit_code" = "0" ]
