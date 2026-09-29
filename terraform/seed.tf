# One-off task for seeding the AOI database, run by hand with `aws ecs run-task`.
#
# The same work can be driven from a laptop through the bastion, but every row
# then crosses the SSM tunnel: reading GADM locally is fine, pushing millions of
# geometries back up is not. In here both hops -- S3 to the task, task to RDS --
# stay on AWS's network.
#
# Sized well above the API: GADM's GeoPackage is ~5GB extracted and the NDJSON
# sources cache to disk before parsing, so this needs real ephemeral storage.
# Run one step per task so each gets a fresh 100GB rather than accumulating.
#
#   scripts/run_seed_task.sh gadm
#
# See scripts/build_seed_db.sh for the steps and their order.

resource "aws_ecs_task_definition" "seed" {
  family                   = "${local.prefix}-seed"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = 8192
  memory                   = 32768
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.task.arn

  ephemeral_storage {
    size_in_gib = 100
  }

  runtime_platform {
    cpu_architecture        = "X86_64"
    operating_system_family = "LINUX"
  }

  container_definitions = jsonencode([
    {
      name      = "seed"
      image     = "${var.image_repository}:${var.image_tag}"
      essential = true

      # Overridden per run by scripts/run_seed_task.sh; this default is a no-op
      # so a bare run-task cannot start a multi-hour ingest by accident.
      command = ["/bin/sh", "-c", "echo 'pass a command override, e.g. scripts/build_seed_db.sh gadm'"]

      secrets = [
        {
          name      = "DATABASE_URL"
          valueFrom = aws_ssm_parameter.database_url.arn
        },
      ]

      environment = [
        { name = "AWS_DEFAULT_REGION", value = var.aws_region },
        { name = "LOG_FORMAT", value = "json" },
        { name = "LOG_TO_FILE", value = "false" },
        { name = "PYTHONUNBUFFERED", value = "1" },
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.seed.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "ecs"
        }
      }
    },
  ])

  tags = local.tags
}

resource "aws_cloudwatch_log_group" "seed" {
  name              = "/aws/ecs/${local.prefix}/seed"
  retention_in_days = 14

  tags = local.tags
}
