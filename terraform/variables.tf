variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "name_prefix" {
  description = <<-EOT
    Prefix for every resource name. Pinned rather than derived from the workspace, so an
    apply from the wrong workspace cannot build a duplicate set of infrastructure.
  EOT
  type        = string
  default     = "horizon-ephemeral"
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

variable "ssm_prefix" {
  description = "SSM parameter path holding secrets written out of band, one parameter per env var name"
  type        = string
  default     = "/horizon-ephemeral"
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
