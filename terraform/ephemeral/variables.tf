variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "shared_prefix" {
  description = <<-EOT
    Name prefix of the shared stack, used to look up its load balancer, cluster,
    database and roles.
  EOT
  type        = string
  default     = "horizon-ephemeral"
}

variable "image_tag" {
  description = <<-EOT
    Commit SHA to deploy; must already exist in the image repository.

    No default: a mutable tag would make a deployment unattributable to a revision.
  EOT
  type        = string
}

variable "image_repository" {
  description = "ECR repository holding the API image"
  type        = string
  default     = "public.ecr.aws/b7u8b0a6/project-zeno/zeno"
}

variable "db_password" {
  description = "Master password for the shared database"
  type        = string
  sensitive   = true
}

variable "db_username" {
  description = "Master username for the shared database"
  type        = string
  default     = "postgres"
}

variable "seed_snapshot_id" {
  description = <<-EOT
    Snapshot holding the reference data. Each deployment restores its own instance from
    it. Its schema version is the floor: commits older than it cannot run, because
    migrations only move forward.
  EOT
  type        = string
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

variable "db_engine_version" {
  description = "Postgres version"
  type        = string
  default     = "17.9"
}

variable "db_instance_class" {
  description = <<-EOT
    RDS instance class.

    Temporarily db.m6g.large: db.t4g.medium had no capacity in this VPC's availability
    zones. Revert once that clears, or widen the subnet group to more zones.
  EOT
  type        = string
  default     = "db.m6g.large"
}

variable "db_storage_type" {
  description = "RDS storage type"
  type        = string
  default     = "gp3"
}

variable "db_max_allocated_storage" {
  description = "Ceiling for storage autoscaling; billed only as used"
  type        = number
  default     = 300
}

variable "ssm_prefix" {
  description = "SSM path holding shared secrets, plus a per-environment DATABASE_URL"
  type        = string
  default     = "/horizon-ephemeral"
}

variable "public_subnet_ids" {
  description = "Subnets for the Fargate tasks; must match the shared ALB's VPC"
  type        = list(string)
  default = [
    "subnet-0f1544432f2a769d2", # us-east-1a
    "subnet-06be7fcbfc68758ff", # us-east-1b
    "subnet-04591b309ac62bf35", # us-east-1c
  ]
}

variable "listener_port_min" {
  description = "Low end of the per-environment listener port range; must match the shared ALB's ingress rule"
  type        = number
  default     = 30000
}

variable "listener_port_max" {
  description = "High end of the per-environment listener port range"
  type        = number
  default     = 31000
}

variable "api_cpu" {
  description = "Fargate CPU units for the API task"
  type        = number
  default     = 2048
}

variable "api_memory" {
  description = "Fargate memory (MiB) for the API task"
  type        = number
  default     = 4096
}

variable "desired_count" {
  description = "API task count. Set to 0 to park an environment without destroying it."
  type        = number
  default     = 1
}

variable "static_data_bucket" {
  description = "Bucket holding the dataset embeddings index"
  type        = string
  default     = "zeno-static-data"
}

variable "env_config" {
  description = "Non-secret environment variables for the API container"
  type        = map(string)
  default = {
    LOG_FORMAT               = "json"
    LOG_LEVEL                = "info"
    LOG_TO_FILE              = "false"
    GNW_STAGE                = "staging"
    AWS_DEFAULT_REGION       = "us-east-1"
    DATASET_EMBEDDINGS_DB    = "gnw-dataset-index-gemini-v8"
    MODEL                    = "gemini-flash"
    SMALL_MODEL              = "gemini-flash"
    CODING_MODEL             = "gemini-3-flash-preview"
    FALLBACK_MODELS          = "gemini,gemini-flash-lite"
    ALLOW_ANONYMOUS_CHAT     = "false"
    MOSAIC_S3_BUCKET         = "gnw-cache"
    MOSAIC_S3_PREFIX         = "mosaics"
    MOSAIC_S3_REGION         = "us-east-1"
    EOAPI_BASE_URL           = "https://eoapi-cache-staging.globalnaturewatch.org"
    LANGFUSE_HOST            = "https://langfuse.staging.globalnaturewatch.org"
    ADMIN_USER_DAILY_QUOTA   = "9999"
    REGULAR_USER_DAILY_QUOTA = "9999"
  }
}

variable "secret_env_names" {
  description = "Env vars read from SSM at <ssm_prefix>/<NAME>, written out of band"
  type        = list(string)
  default = [
    "GOOGLE_API_KEY",
    "ANTHROPIC_API_KEY",
    "WRI_BEARER_TOKEN",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
  ]
}
