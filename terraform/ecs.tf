# --- IAM -------------------------------------------------------------------
# Unlike project-zeno-data-infra, application permissions live on a dedicated
# task role rather than on the execution role, and the container reads S3 via
# that role instead of static AWS keys.

data "aws_iam_policy_document" "task_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "task_execution" {
  name               = "${local.prefix}-task-execution"
  assume_role_policy = data.aws_iam_policy_document.task_assume.json
  tags               = local.tags
}

resource "aws_iam_role_policy_attachment" "task_execution_managed" {
  role       = aws_iam_role.task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# The execution role pulls secrets at task start; the task role never needs to.
data "aws_iam_policy_document" "task_execution_secrets" {
  statement {
    effect  = "Allow"
    actions = ["ssm:GetParameters"]
    resources = concat(
      [aws_ssm_parameter.database_url.arn],
      [for name in var.secret_env_names : "${local.secret_arn_prefix}/${name}"],
    )
  }
}

resource "aws_iam_policy" "task_execution_secrets" {
  name   = "${local.prefix}-task-execution-secrets"
  policy = data.aws_iam_policy_document.task_execution_secrets.json
  tags   = local.tags
}

resource "aws_iam_role_policy_attachment" "task_execution_secrets" {
  role       = aws_iam_role.task_execution.name
  policy_arn = aws_iam_policy.task_execution_secrets.arn
}

resource "aws_iam_role" "task" {
  name               = "${local.prefix}-task"
  assume_role_policy = data.aws_iam_policy_document.task_assume.json
  tags               = local.tags
}

data "aws_iam_policy_document" "task_s3" {
  statement {
    effect  = "Allow"
    actions = ["s3:GetObject", "s3:ListBucket"]
    resources = [
      "arn:aws:s3:::${var.static_data_bucket}",
      "arn:aws:s3:::${var.static_data_bucket}/*",
      "arn:aws:s3:::${var.env_config["MOSAIC_S3_BUCKET"]}",
      "arn:aws:s3:::${var.env_config["MOSAIC_S3_BUCKET"]}/*",
    ]
  }
}

resource "aws_iam_policy" "task_s3" {
  name   = "${local.prefix}-task-s3"
  policy = data.aws_iam_policy_document.task_s3.json
  tags   = local.tags
}

resource "aws_iam_role_policy_attachment" "task_s3" {
  role       = aws_iam_role.task.name
  policy_arn = aws_iam_policy.task_s3.arn
}

# --- load balancer ---------------------------------------------------------
# Raw ALB DNS over HTTP: the account has no Route53 hosted zone, so there is no
# record for Terraform to create.

module "alb" {
  source  = "terraform-aws-modules/alb/aws"
  version = "~> 9.0"

  name               = local.prefix
  load_balancer_type = "application"

  vpc_id  = var.vpc_id
  subnets = var.public_subnet_ids

  enable_deletion_protection = false

  security_group_ingress_rules = {
    all_http = {
      from_port   = 80
      to_port     = 80
      ip_protocol = "tcp"
      cidr_ipv4   = "0.0.0.0/0"
    }
  }

  security_group_egress_rules = {
    all = {
      ip_protocol = "-1"
      cidr_ipv4   = data.aws_vpc.selected.cidr_block
    }
  }

  listeners = {
    http = {
      port     = 80
      protocol = "HTTP"
      forward  = { target_group_key = "api" }
    }
  }

  target_groups = {
    api = {
      backend_protocol                  = "HTTP"
      backend_port                      = 8000
      target_type                       = "ip"
      deregistration_delay              = 5
      load_balancing_cross_zone_enabled = true

      health_check = {
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

      # ECS registers its own targets.
      create_attachment = false
    }
  }

  tags = local.tags
}

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

module "api" {
  source  = "terraform-aws-modules/ecs/aws//modules/service"
  version = "6.3.0"

  name        = local.prefix
  cluster_arn = module.ecs_cluster.arn

  cpu           = var.api_cpu
  memory        = var.api_memory
  desired_count = var.desired_count

  create_task_exec_iam_role = false
  task_exec_iam_role_arn    = aws_iam_role.task_execution.arn
  create_tasks_iam_role     = false
  tasks_iam_role_arn        = aws_iam_role.task.arn

  enable_autoscaling                 = false
  assign_public_ip                   = true
  health_check_grace_period_seconds  = 120
  deployment_minimum_healthy_percent = 0

  deployment_circuit_breaker = {
    enable   = true
    rollback = true
  }

  container_definitions = {
    # ECS has no init containers. This mirrors the Helm pod's s3-data-sync init
    # container: the dataset embeddings index named by DATASET_EMBEDDINGS_DB is
    # not baked into the image, and pick_dataset throws without it.
    data-sync = {
      image     = "amazon/aws-cli:latest"
      essential = false
      # Fetch only the dataset embeddings index -- one object, under 1MB.
      #
      # The Helm chart syncs the entire bucket, but that is ~5700 mostly tiny
      # objects and takes minutes: long enough that the API never starts inside
      # the load balancer's health check grace period, so ECS kills the task and
      # the replacement re-syncs from an empty volume forever. Almost all of it
      # is redundant anyway -- the Dockerfile bakes the insights corpus and sgrep
      # index into the image at build time from the wri-insights/ tarball.
      #
      # This is the one runtime file the image does not carry; without it
      # pick_dataset throws on the first query that selects a dataset.
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

      # The Dockerfile declares no CMD or ENTRYPOINT, so the command is required.
      #
      # Migrations run here rather than as a separate job, the way gfw-data-api's
      # prestart.sh does: this service runs a single task, so there is nothing to
      # race with, and it means a restored snapshot is always brought up to the
      # deployed commit's revision without a separate step to forget.
      command = [
        "/bin/sh", "-c",
        "/app/db/migrate.sh && exec uv run uvicorn src.api.app:app --host 0.0.0.0 --port 8000",
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
          { API_BASE_URL = "http://${module.alb.dns_name}" },
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
      target_group_arn = module.alb.target_groups["api"].arn
      container_name   = "api"
      container_port   = 8000
    }
  }

  subnet_ids         = var.public_subnet_ids
  security_group_ids = [aws_security_group.api.id]

  # The SG is declared above; the module would otherwise create its own.
  create_security_group = false

  tags = local.tags
}
