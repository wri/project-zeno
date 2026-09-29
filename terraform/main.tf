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
  name_suffix = terraform.workspace == "default" ? "" : "-${terraform.workspace}"
  prefix      = "zeno-evals${local.name_suffix}"

  tags = {
    Project   = "Zeno"
    Component = "evals"
    Workspace = terraform.workspace
    ManagedBy = "terraform"
  }

  # Maintenance connection: you cannot drop or clone a database while connected
  # to it, so this points elsewhere.
  maintenance_database_url = format(
    "postgresql://%s:%s@%s/template1",
    var.db_username,
    var.db_password,
    aws_db_instance.evals.address,
  )

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
  description = "Security group for the evals API service"

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

resource "aws_security_group" "db" {
  name_prefix = "${local.prefix}-db-"
  vpc_id      = var.vpc_id
  description = "Security group for the evals database"

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.api.id]
    description     = "Allow the API and one-off tasks to reach Postgres"
  }

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.bastion.id]
    description     = "Allow the bastion to reach Postgres for seeding and ad-hoc psql"
  }

  tags = merge(local.tags, { Name = "${local.prefix}-db" })

  lifecycle {
    create_before_destroy = true
  }
}

# --- database --------------------------------------------------------------
# Shared instance. Restored from a snapshot holding the reference data; nothing
# here populates it.

resource "aws_db_subnet_group" "evals" {
  name       = local.prefix
  subnet_ids = var.private_subnet_ids

  tags = merge(local.tags, { Name = local.prefix })
}

resource "aws_db_instance" "evals" {
  identifier = "${local.prefix}-db"

  # Empty creates an empty instance; set restores that snapshot.
  snapshot_identifier = var.seed_snapshot_id != "" ? var.seed_snapshot_id : null

  engine                = "postgres"
  engine_version        = var.db_engine_version
  instance_class        = var.db_instance_class
  allocated_storage     = var.db_allocated_storage
  max_allocated_storage = var.db_max_allocated_storage
  storage_encrypted     = var.db_storage_encrypted

  # Settable only when creating fresh; a restore inherits it, and setting it
  # would force replacement.
  username = var.seed_snapshot_id != "" ? null : var.db_username
  password = var.db_password

  db_subnet_group_name   = aws_db_subnet_group.evals.name
  vpc_security_group_ids = [aws_security_group.db.id]
  publicly_accessible    = false

  # Disposable: rebuildable from the snapshot.
  backup_retention_period = 0
  skip_final_snapshot     = true
  apply_immediately       = true

  tags = merge(local.tags, { Name = "${local.prefix}-db" })

  lifecycle {
    # Only meaningful at creation. Ignoring later changes stops a snapshot being
    # pinned after the fact from replacing a populated instance.
    ignore_changes = [snapshot_identifier]
  }
}

# Derived from the endpoint, so it cannot be written out of band like the other
# secrets. Held in SSM to keep the password out of task definitions.
resource "aws_ssm_parameter" "maintenance_database_url" {
  name        = "${var.ssm_prefix}/MAINTENANCE_DATABASE_URL"
  description = "template1 connection, used to create and drop per-environment databases"
  type        = "SecureString"
  value       = local.maintenance_database_url

  tags = local.tags
}
