terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~>6"
    }
  }
}

terraform {
  backend "s3" {
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = var.aws_region
}

data "aws_caller_identity" "current" {}

locals {
  # One workspace per deployment; its name decides every derived value below.
  env_name = terraform.workspace
  prefix   = "${var.shared_prefix}-${local.env_name}"

  # Deployments share one load balancer and are separated by port. Derived from
  # the name so it is stable across applies; a collision means renaming one.
  listener_port = var.listener_port_min + parseint(substr(sha256(local.env_name), 0, 4), 16) % (var.listener_port_max - var.listener_port_min)

  database_url = format(
    "postgresql+asyncpg://%s:%s@%s/postgres",
    var.db_username,
    var.db_password,
    aws_db_instance.main.address,
  )

  secret_arn_prefix = "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${var.ssm_prefix}"

  tags = {
    Project     = "Horizon"
    Component   = "ephemeral-env"
    Environment = local.env_name
    Commit      = var.image_tag
    ManagedBy   = "terraform"
  }
}

# --- shared infrastructure, looked up by name ------------------------------

data "aws_lb" "shared" {
  name = var.shared_prefix
}

data "aws_ecs_cluster" "shared" {
  cluster_name = var.shared_prefix
}

data "aws_iam_role" "task_execution" {
  name = "${var.shared_prefix}-task-execution"
}

data "aws_iam_role" "task" {
  name = "${var.shared_prefix}-task"
}

data "aws_security_group" "task" {
  filter {
    name   = "tag:Name"
    values = ["${var.shared_prefix}-api"]
  }
}

data "aws_security_group" "bastion" {
  filter {
    name   = "tag:Name"
    values = ["${var.shared_prefix}-bastion"]
  }
}

# Connection string for this deployment's own instance.

resource "aws_ssm_parameter" "database_url" {
  name        = "${var.ssm_prefix}/${local.env_name}/DATABASE_URL"
  description = "Connection string for deployment ${local.env_name}"
  type        = "SecureString"
  value       = local.database_url

  tags = local.tags
}
