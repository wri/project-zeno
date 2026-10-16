# Target group and listener for this deployment, on the shared load balancer.

resource "aws_lb_target_group" "api" {
  name        = substr("${local.prefix}", 0, 32)
  port        = 8000
  protocol    = "HTTP"
  target_type = "ip" # required for Fargate
  vpc_id      = data.aws_lb.shared.vpc_id

  deregistration_delay              = 5
  load_balancing_cross_zone_enabled = true

  health_check {
    enabled             = true
    path                = "/openapi.json"
    port                = "traffic-port"
    protocol            = "HTTP"
    matcher             = "200"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 5
  }

  tags = local.tags

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_lb_listener" "api" {
  load_balancer_arn = data.aws_lb.shared.arn
  port              = local.listener_port
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }

  tags = local.tags
}

module "api" {
  source  = "terraform-aws-modules/ecs/aws//modules/service"
  version = "6.3.0"

  name        = local.prefix
  cluster_arn = data.aws_ecs_cluster.shared.arn

  cpu           = var.api_cpu
  memory        = var.api_memory
  desired_count = var.desired_count

  create_task_exec_iam_role = false
  task_exec_iam_role_arn    = data.aws_iam_role.task_execution.arn
  create_tasks_iam_role     = false
  tasks_iam_role_arn        = data.aws_iam_role.task.arn

  enable_autoscaling                 = false
  assign_public_ip                   = true
  health_check_grace_period_seconds  = 180
  deployment_minimum_healthy_percent = 0

  deployment_circuit_breaker = {
    enable   = true
    rollback = true
  }

  container_definitions = {
    # Fetches the dataset embeddings index, which the image does not carry.
    # Runs to completion before the api container starts.
    data-sync = {
      image     = "amazon/aws-cli:latest"
      essential = false

      command = [
        "s3", "cp",
        "s3://${var.static_data_bucket}/${var.env_config["DATASET_EMBEDDINGS_DB"]}",
        "/app/data/${var.env_config["DATASET_EMBEDDINGS_DB"]}",
      ]

      mountPoints = [{
        sourceVolume  = "data"
        containerPath = "/app/data"
        readOnly      = false
      }]

      enable_cloudwatch_logging = true
    }

    api = {
      image     = "${var.image_repository}:${var.image_tag}"
      essential = true

      # The image declares no entrypoint. Migrate, then serve.
      command = [
        "/bin/sh", "-c",
        "/app/db/migrate.sh && exec uv run --no-sync uvicorn src.api.app:app --host 0.0.0.0 --port 8000",
      ]

      portMappings = [{
        name          = "api"
        containerPort = 8000
        hostPort      = 8000
        protocol      = "tcp"
      }]

      dependsOn = [{
        containerName = "data-sync"
        condition     = "SUCCESS"
      }]

      mountPoints = [{
        sourceVolume  = "data"
        containerPath = "/app/data"
        readOnly      = false
      }]

      environment = [
        for name, value in merge(
          var.env_config,
          {
            API_BASE_URL    = "http://${data.aws_lb.shared.dns_name}:${local.listener_port}"
            DEPLOYMENT_NAME = local.env_name
          },
        ) : { name = name, value = value }
      ]

      secrets = concat(
        [{ name = "DATABASE_URL", valueFrom = aws_ssm_parameter.database_url.arn }],
        [for name in var.secret_env_names : {
          name      = name
          valueFrom = "${local.secret_arn_prefix}/${name}"
        }],
      )

      readonlyRootFilesystem    = false
      enable_cloudwatch_logging = true
    }
  }

  volume = {
    data = {}
  }

  load_balancer = {
    api = {
      target_group_arn = aws_lb_target_group.api.arn
      container_name   = "api"
      container_port   = 8000
    }
  }

  subnet_ids            = var.public_subnet_ids
  security_group_ids    = [data.aws_security_group.task.id]
  create_security_group = false

  depends_on = [aws_lb_listener.api]

  tags = local.tags
}
