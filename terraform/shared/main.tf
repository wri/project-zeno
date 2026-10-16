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
    encrypt = true
  }
}

provider "aws" {
  region = var.aws_region
}

data "aws_caller_identity" "current" {}
data "aws_availability_zones" "available" {}

locals {
  prefix = var.name_prefix

  tags = {
    Project   = "Horizon"
    Component = "ephemeral-env"
    Workspace = terraform.workspace
    ManagedBy = "terraform"
  }

  secret_arn_prefix = "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${var.ssm_prefix}"
}

# --- networking ------------------------------------------------------------
# Pre-existing, shared VPC. Tasks run in public subnets with public IPs; the
# database sits in private subnets and is never publicly reachable.

data "aws_vpc" "selected" {
  id = var.vpc_id
}

# --- security groups -------------------------------------------------------

resource "aws_security_group" "api" {
  name_prefix = "${local.prefix}-api-"
  vpc_id      = var.vpc_id
  description = "Security group for deployment API services"

  ingress {
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [module.alb.security_group_id]
    description     = "Allow ALB to reach the API"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Allow all outbound traffic"
  }

  tags = merge(local.tags, { Name = "${local.prefix}-api" })

  lifecycle {
    create_before_destroy = true
  }
}
