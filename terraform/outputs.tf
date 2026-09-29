output "cluster_name" {
  description = "ECS cluster shared by every ephemeral environment"
  value       = module.ecs_cluster.name
}

output "alb_dns_name" {
  description = "Shared ALB hostname; environments are reached at http://<this>:<port>"
  value       = module.alb.dns_name
}

output "alb_arn" {
  description = "Shared ALB, for per-environment listeners"
  value       = module.alb.arn
}

output "db_address" {
  description = "Endpoint of the shared evals database"
  value       = aws_db_instance.evals.address
}

output "db_instance_identifier" {
  description = "RDS instance identifier, for snapshot commands"
  # .identifier, not .id: the latter is the resource id, which the snapshot APIs
  # do not accept.
  value = aws_db_instance.evals.identifier
}

output "bastion_instance_id" {
  description = "Bastion to port-forward through with `aws ssm start-session`"
  value       = aws_instance.bastion.id
}

output "teardown_task_definition_arn" {
  description = "Task that drops an environment's database, run during teardown"
  value       = aws_ecs_task_definition.teardown.arn
}

output "task_subnet_ids" {
  description = "Subnets for environment services and one-off tasks"
  value       = var.public_subnet_ids
}

output "task_security_group_id" {
  description = "Security group for environment services and one-off tasks"
  value       = aws_security_group.api.id
}
