output "api_base_url" {
  description = "Base URL for the evals API; pass this to gnw_evals as API_BASE_URL"
  value       = "http://${module.alb.dns_name}"
}

output "cluster_name" {
  description = "ECS cluster name"
  value       = module.ecs_cluster.name
}

output "service_name" {
  description = "ECS service name, for `aws ecs update-service --force-new-deployment`"
  value       = module.api.name
}

output "task_subnet_ids" {
  description = "Subnets, for running one-off tasks against this environment"
  value       = var.public_subnet_ids
}

output "task_security_group_id" {
  description = "Security group, for running one-off tasks against this environment"
  value       = aws_security_group.api.id
}

output "db_address" {
  description = "Endpoint of the restored evals database"
  value       = aws_db_instance.evals.address
}

output "db_instance_identifier" {
  description = "RDS instance to point scripts/build_seed_db.sh at"
  # .identifier, not .id: the latter is the DBI resource id (db-XXXX...), which
  # the RDS snapshot APIs do not accept.
  value = aws_db_instance.evals.identifier
}

output "bastion_instance_id" {
  description = "Bastion to port-forward through with `aws ssm start-session`"
  value       = aws_instance.bastion.id
}

output "seed_task_definition_arn" {
  description = "One-off task for seeding the AOI database, driven by scripts/run_seed_task.sh"
  value       = aws_ecs_task_definition.seed.arn
}

output "seed_log_group" {
  description = "CloudWatch log group for seed task runs"
  value       = aws_cloudwatch_log_group.seed.name
}
