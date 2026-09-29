# Drops a deployment's database during teardown. The database name is passed as
# a command override at run time.
#
# Shared rather than per-deployment, so it outlives the thing it cleans up.

resource "aws_ecs_task_definition" "teardown" {
  family                   = "${local.prefix}-teardown"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    cpu_architecture        = "X86_64"
    operating_system_family = "LINUX"
  }

  container_definitions = jsonencode([
    {
      name      = "teardown"
      image     = "postgres:17-alpine"
      essential = true

      # Overridden per run; this default is a deliberate no-op.
      command = ["sh", "-c", "echo 'pass a command override naming the database to drop'"]

      secrets = [
        {
          name      = "MAINTENANCE_DATABASE_URL"
          valueFrom = aws_ssm_parameter.maintenance_database_url.arn
        },
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.teardown.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "ecs"
        }
      }
    },
  ])

  tags = local.tags
}

resource "aws_cloudwatch_log_group" "teardown" {
  name              = "/aws/ecs/${local.prefix}/teardown"
  retention_in_days = 14

  tags = local.tags
}
