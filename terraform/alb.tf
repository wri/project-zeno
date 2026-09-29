# Shared load balancer. Each deployment adds its own listener and target group
# on its own port, so one balancer serves all of them.

module "alb" {
  source  = "terraform-aws-modules/alb/aws"
  version = "~> 9.0"

  name               = local.prefix
  load_balancer_type = "application"

  vpc_id  = var.vpc_id
  subnets = var.public_subnet_ids

  enable_deletion_protection = false

  # The whole port range, opened once rather than a rule per deployment.
  security_group_ingress_rules = {
    ephemeral_envs = {
      from_port   = var.env_listener_port_min
      to_port     = var.env_listener_port_max
      ip_protocol = "tcp"
      cidr_ipv4   = "0.0.0.0/0"
      description = "Per-environment listeners"
    }
  }

  security_group_egress_rules = {
    all = {
      ip_protocol = "-1"
      cidr_ipv4   = data.aws_vpc.selected.cidr_block
    }
  }

  tags = local.tags
}
