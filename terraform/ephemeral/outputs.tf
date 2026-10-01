output "api_base_url" {
  description = "Base URL for this deployment"
  value       = "http://${data.aws_lb.shared.dns_name}:${local.listener_port}"
}

output "listener_port" {
  description = "Port this environment listens on, derived from the workspace name"
  value       = local.listener_port
}

output "db_instance_identifier" {
  description = "This deployment's database instance"
  value       = aws_db_instance.main.identifier
}

output "service_name" {
  description = "ECS service name"
  value       = module.api.name
}

output "cluster_name" {
  description = "Shared ECS cluster"
  value       = data.aws_ecs_cluster.shared.cluster_name
}
