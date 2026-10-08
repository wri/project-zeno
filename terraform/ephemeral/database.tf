# One database instance per deployment, restored from the reference snapshot.
#
# Restoring is fast because RDS hydrates the volume from S3 lazily, so the
# instance is usable in a few minutes; early queries are slower until blocks
# fault in. Cloning a database on a shared instance was tried instead and took
# far longer, because that copy is eager and throttled by the instance's own IO.

resource "aws_db_subnet_group" "main" {
  name       = local.prefix
  subnet_ids = var.private_subnet_ids

  tags = merge(local.tags, { Name = local.prefix })
}

resource "aws_security_group" "db" {
  name_prefix = "${local.prefix}-db-"
  vpc_id      = data.aws_lb.shared.vpc_id
  description = "Database for deployment ${local.env_name}"

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [data.aws_security_group.task.id]
    description     = "Allow this deployment tasks to reach Postgres"
  }

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [data.aws_security_group.bastion.id]
    description     = "Allow the bastion to reach Postgres for ad-hoc psql"
  }

  tags = merge(local.tags, { Name = "${local.prefix}-db" })

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_db_instance" "main" {
  identifier          = "${local.prefix}-db"
  snapshot_identifier = var.seed_snapshot_id

  engine                = "postgres"
  engine_version        = var.db_engine_version
  instance_class        = var.db_instance_class
  max_allocated_storage = var.db_max_allocated_storage
  storage_type          = var.db_storage_type

  # Inherited from the snapshot; setting it would force replacement.
  password = var.db_password

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.db.id]
  publicly_accessible    = false

  # Disposable: the snapshot is the only copy worth keeping.
  backup_retention_period = 0
  skip_final_snapshot     = true
  apply_immediately       = true

  tags = merge(local.tags, { Name = "${local.prefix}-db" })
}
