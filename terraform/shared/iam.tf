# Application permissions live on the task role; the execution role only pulls
# images and resolves secrets.

data "aws_iam_policy_document" "task_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "task_execution" {
  name               = "${local.prefix}-task-execution"
  assume_role_policy = data.aws_iam_policy_document.task_assume.json
  tags               = local.tags
}

resource "aws_iam_role_policy_attachment" "task_execution_managed" {
  role       = aws_iam_role.task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}


# Wildcard: deployments write their own connection strings under this prefix.
data "aws_iam_policy_document" "task_execution_secrets" {
  statement {
    effect    = "Allow"
    actions   = ["ssm:GetParameters"]
    resources = ["${local.secret_arn_prefix}/*", local.secret_arn_prefix]
  }
}

resource "aws_iam_policy" "task_execution_secrets" {
  name   = "${local.prefix}-task-execution-secrets"
  policy = data.aws_iam_policy_document.task_execution_secrets.json
  tags   = local.tags
}

resource "aws_iam_role_policy_attachment" "task_execution_secrets" {
  role       = aws_iam_role.task_execution.name
  policy_arn = aws_iam_policy.task_execution_secrets.arn
}

resource "aws_iam_role" "task" {
  name               = "${local.prefix}-task"
  assume_role_policy = data.aws_iam_policy_document.task_assume.json
  tags               = local.tags
}

data "aws_iam_policy_document" "task_s3" {
  statement {
    effect  = "Allow"
    actions = ["s3:GetObject", "s3:ListBucket"]
    resources = [
      "arn:aws:s3:::${var.static_data_bucket}",
      "arn:aws:s3:::${var.static_data_bucket}/*",
      "arn:aws:s3:::${var.mosaic_bucket}",
      "arn:aws:s3:::${var.mosaic_bucket}/*",
    ]
  }
}

resource "aws_iam_policy" "task_s3" {
  name   = "${local.prefix}-task-s3"
  policy = data.aws_iam_policy_document.task_s3.json
  tags   = local.tags
}

resource "aws_iam_role_policy_attachment" "task_s3" {
  role       = aws_iam_role.task.name
  policy_arn = aws_iam_policy.task_s3.arn
}

# --- load balancer ---------------------------------------------------------
# Raw ALB DNS over HTTP: the account has no Route53 hosted zone, so there is no
# record for Terraform to create.
