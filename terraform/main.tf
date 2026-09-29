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
  # Matches the project-zeno-data-infra idiom: the "default" workspace is the
  # unsuffixed environment, every other workspace suffixes every resource name.
  name_suffix = terraform.workspace == "default" ? "" : "-${terraform.workspace}"
  prefix      = "zeno-evals${local.name_suffix}"

  tags = {
    Project   = "Zeno"
    Component = "evals"
    Workspace = terraform.workspace
    ManagedBy = "terraform"
  }

  # The API expects the +asyncpg form; db/alembic/env.py and src/agent/graph.py
  # rewrite it themselves for psycopg.
  database_url = format(
    "postgresql+asyncpg://%s:%s@%s/%s",
    var.db_username,
    var.db_password,
    aws_db_instance.evals.address,
    var.db_name,
  )

  secret_arn_prefix = "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${var.ssm_prefix}"
}

# --- networking ------------------------------------------------------------
# The VPC is pre-existing and shared (see var.vpc_id). Tasks run in public
# subnets with public IPs, matching project-zeno-data-infra; the database sits in
# private subnets and is never publicly reachable.

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
# Restored from the snapshot built by scripts/build_seed_db.sh. Nothing here
# ingests AOIs: an empty database would leave `aois` empty and the API unable to
# resolve any area.

resource "aws_db_subnet_group" "evals" {
  name       = local.prefix
  subnet_ids = var.private_subnet_ids

  tags = merge(local.tags, { Name = local.prefix })
}

resource "aws_db_instance" "evals" {
  identifier = "${local.prefix}-db"

  # Empty means "create an empty database" (bootstrap, to be filled by
  # scripts/build_seed_db.sh); set means "restore that snapshot".
  snapshot_identifier = var.seed_snapshot_id != "" ? var.seed_snapshot_id : null

  engine            = "postgres"
  engine_version    = var.db_engine_version
  instance_class    = var.db_instance_class
  allocated_storage = var.db_allocated_storage

  # username can only be set when creating fresh. On a restore it is inherited
  # from the snapshot, and setting it would force replacement -- so it is null
  # there and var.db_username only builds DATABASE_URL. password is settable in
  # both modes and overrides whatever the snapshot carried.
  username = var.seed_snapshot_id != "" ? null : var.db_username
  password = var.db_password

  db_subnet_group_name   = aws_db_subnet_group.evals.name
  vpc_security_group_ids = [aws_security_group.db.id]
  publicly_accessible    = false

  # Evals data is disposable: it can always be rebuilt from the seed snapshot.
  backup_retention_period = 0
  skip_final_snapshot     = true
  apply_immediately       = true

  tags = merge(local.tags, { Name = "${local.prefix}-db" })

  lifecycle {
    # snapshot_identifier is ForceNew, so pinning a snapshot after bootstrap
    # would destroy the database the seed script just filled. It only has
    # meaning at creation, so later changes are ignored: existing instances are
    # left alone, new ones still restore.
    ignore_changes = [snapshot_identifier]
  }
}

# DATABASE_URL is derived from the RDS endpoint, so it cannot be pre-written out
# of band like the other secrets. Holding it in SSM keeps the password out of the
# task definition, where DescribeTaskDefinition would expose it.
resource "aws_ssm_parameter" "database_url" {
  # Workspace-scoped: at a fixed path a bootstrap run would overwrite another
  # environment's connection string. Shared secrets stay unscoped.
  name        = "${var.ssm_prefix}/${terraform.workspace}/DATABASE_URL"
  description = "Connection string for the evals database"
  type        = "SecureString"
  value       = local.database_url

  tags = local.tags
}
