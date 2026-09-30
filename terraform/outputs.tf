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

output "bastion_instance_id" {
  description = "Bastion to port-forward through with `aws ssm start-session`"
  value       = aws_instance.bastion.id
}

output "task_subnet_ids" {
  description = "Subnets for environment services and one-off tasks"
  value       = var.public_subnet_ids
}

output "task_security_group_id" {
  description = "Security group for environment services and one-off tasks"
  value       = aws_security_group.api.id
}
