variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "vpc_id" {
  description = <<-EOT
    Pre-existing VPC to deploy into; this stack does not create one, because the
    account is at its VPC quota. Switch to a dedicated VPC when isolation matters.
  EOT
  type        = string
  default     = "vpc-0233b677bf7586002"
}

variable "public_subnet_ids" {
  description = "Public subnets for the ALB, the Fargate tasks and the bastion"
  type        = list(string)
  default = [
    "subnet-0f1544432f2a769d2", # us-east-1a
    "subnet-06be7fcbfc68758ff", # us-east-1b
    "subnet-04591b309ac62bf35", # us-east-1c
  ]
}

variable "private_subnet_ids" {
  description = "Private subnets for the database"
  type        = list(string)
  default = [
    "subnet-093dc828845e30d17", # us-east-1a
    "subnet-06a71eea1358f008f", # us-east-1b
    "subnet-061f3f293ed2f3f5e", # us-east-1c
  ]
}

variable "seed_snapshot_id" {
  description = <<-EOT
    Snapshot holding the reference data to restore from.

    No default: an empty value creates an empty instance, which is right for a first
    bring-up and destructive on a replace, so it must always be stated.
  EOT
  type        = string
}

variable "db_engine_version" {
  description = "Postgres version, matching staging"
  type        = string
  default     = "17.9"
}

variable "db_instance_class" {
  description = "RDS instance class (staging uses db.t4g.medium)"
  type        = string
  default     = "db.t4g.medium"
}

variable "db_allocated_storage" {
  description = "Storage (GB). Ignored on a snapshot restore unless larger than the snapshot."
  type        = number
  default     = 100
}

variable "db_max_allocated_storage" {
  description = <<-EOT
    Ceiling for storage autoscaling. Each deployment's database is a full copy of the
    template, so abandoned ones are what fill the volume. Billed only as used.
  EOT
  type        = number
  default     = 300
}

variable "db_storage_encrypted" {
  description = <<-EOT
    Encrypt at rest. False by default because enabling it replaces the instance, and an
    unencrypted snapshot must be copied with a KMS key before it can be restored into an
    encrypted one. Set true on a new instance.
  EOT
  type        = bool
  default     = false
}

variable "db_password" {
  description = "Master password. A snapshot restore keeps the source password unless this overrides it."
  type        = string
  sensitive   = true
}

variable "db_username" {
  description = "Master username, inherited from the snapshot"
  type        = string
  default     = "postgres"
}

variable "ssm_prefix" {
  description = "SSM parameter path holding secrets written out of band, one parameter per env var name"
  type        = string
  default     = "/zeno/evals"
}

variable "static_data_bucket" {
  description = "Bucket holding the dataset embeddings index"
  type        = string
  default     = "zeno-static-data"
}

variable "mosaic_bucket" {
  description = "Bucket backing the /mosaic tile endpoints"
  type        = string
  default     = "gnw-cache"
}

variable "env_listener_port_min" {
  description = "Low end of the per-environment listener port range"
  type        = number
  default     = 30000
}

variable "env_listener_port_max" {
  description = "High end of the per-environment listener port range"
  type        = number
  default     = 31000
}
