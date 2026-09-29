variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "vpc_id" {
  description = <<-EOT
    VPC to deploy into. Defaults to vpc-zeno-staging, which project-zeno-data-infra
    already shares -- the account is at its 5-VPC quota, so this stack does not create
    its own. Raise the quota and switch to a dedicated VPC when isolation matters.
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

variable "image_tag" {
  description = "project-zeno commit SHA to deploy. Must already exist in the public ECR repo."
  type        = string
  default     = "latest"
}

variable "image_repository" {
  description = "ECR repository holding the API image"
  type        = string
  default     = "public.ecr.aws/b7u8b0a6/project-zeno/zeno"
}

variable "seed_snapshot_id" {
  description = <<-EOT
    RDS snapshot to restore the AOI database from, built by scripts/build_seed_db.sh.

    Leave empty to create a fresh, EMPTY database. That is bootstrap mode: run the
    seed script against it and snapshot the result. Any environment actually serving
    evals must set this, because an empty `aois` table means the API cannot resolve
    any area.
  EOT
  type        = string
  default     = ""
}

variable "db_engine_version" {
  description = "Postgres version, matching staging"
  type        = string
  default     = "17.9"
}

variable "db_allocated_storage" {
  description = "Storage (GB). Ignored on a snapshot restore unless larger than the snapshot."
  type        = number
  default     = 100
}

variable "db_instance_class" {
  description = "RDS instance class (staging uses db.t4g.medium)"
  type        = string
  default     = "db.t4g.medium"
}

variable "db_password" {
  description = "Master password for the restored database. A snapshot restore keeps the source password unless this overrides it."
  type        = string
  sensitive   = true
}

variable "db_username" {
  description = "Master username, inherited from the snapshot"
  type        = string
  default     = "postgres"
}

variable "db_name" {
  description = <<-EOT
    Database name in DATABASE_URL. Empty matches the Helm charts, where POSTGRES_DB is
    unset and the server falls back to the `postgres` database.
  EOT
  type        = string
  default     = ""
}

variable "ssm_prefix" {
  description = "SSM parameter path holding secrets written out of band, one parameter per env var name"
  type        = string
  default     = "/zeno/evals"
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
  description = "API task count. Set to 0 to park the environment between eval runs."
  type        = number
  default     = 1
}

variable "static_data_bucket" {
  description = "Bucket synced into /app/data before the API starts, supplying the dataset embeddings index"
  type        = string
  default     = "zeno-static-data"
}

variable "env_config" {
  description = "Non-secret environment variables for the API container"
  type        = map(string)
  default = {
    LOG_FORMAT             = "json"
    LOG_LEVEL              = "info"
    LOG_TO_FILE            = "false"
    GNW_STAGE              = "staging"
    AWS_DEFAULT_REGION     = "us-east-1"
    DATASET_EMBEDDINGS_DB  = "gnw-dataset-index-gemini-v8"
    MODEL                  = "gemini-flash"
    SMALL_MODEL            = "gemini-flash"
    CODING_MODEL           = "gemini-3-flash-preview"
    FALLBACK_MODELS        = "gemini,gemini-flash-lite"
    ALLOW_ANONYMOUS_CHAT   = "false"
    MOSAIC_S3_BUCKET       = "gnw-cache"
    MOSAIC_S3_PREFIX       = "mosaics"
    MOSAIC_S3_REGION       = "us-east-1"
    EOAPI_BASE_URL         = "https://eoapi-cache-staging.globalnaturewatch.org"
    LANGFUSE_HOST          = "https://langfuse.staging.globalnaturewatch.org"
    ADMIN_USER_DAILY_QUOTA = "9999"
  }
}

variable "secret_env_names" {
  description = <<-EOT
    Env vars read from SSM at <ssm_prefix>/<NAME>. Write these out of band with
    `aws ssm put-parameter --type SecureString`; Terraform only reads their ARNs so the
    values never enter state. DATABASE_URL is excluded: it is derived from the RDS
    endpoint and written by this stack.
  EOT
  type        = list(string)
  default = [
    "GOOGLE_API_KEY",
    "ANTHROPIC_API_KEY",
    "WRI_BEARER_TOKEN",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
  ]
}
