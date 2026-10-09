# --- ECS -------------------------------------------------------------------

module "ecs_cluster" {
  source  = "terraform-aws-modules/ecs/aws//modules/cluster"
  version = "6.3.0"

  name = local.prefix

  # Roles are declared above so the task role is distinct from the execution role.
  create_task_exec_iam_role = false

  default_capacity_provider_strategy = {
    FARGATE = { weight = 100 }
  }

  tags = local.tags
}
