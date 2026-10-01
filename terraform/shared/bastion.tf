# Bastion for reaching the private database from a laptop, via SSM port
# forwarding:
#
#   aws ssm start-session --target $(terraform output -raw bastion_instance_id) \
#     --document-name AWS-StartPortForwardingSessionToRemoteHost \
#     --parameters host=$(terraform output -raw db_address),portNumber=5432,localPortNumber=5432
#
# It has a public IP but no inbound rules and no key pair: the agent dials out,
# and access is authorized by IAM. Do not add a key pair -- that invites SSH, and
# with it an open port.

data "aws_ami" "bastion" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-arm64"]
  }
}

data "aws_iam_policy_document" "bastion_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "bastion" {
  name               = "${local.prefix}-bastion"
  assume_role_policy = data.aws_iam_policy_document.bastion_assume.json
  tags               = local.tags
}

resource "aws_iam_role_policy_attachment" "bastion_ssm" {
  role       = aws_iam_role.bastion.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "bastion" {
  name = "${local.prefix}-bastion"
  role = aws_iam_role.bastion.name
  tags = local.tags
}

resource "aws_security_group" "bastion" {
  name_prefix = "${local.prefix}-bastion-"
  vpc_id      = var.vpc_id
  description = "Security group for the bastion"

  # No ingress rules. SSM needs none.

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Allow outbound to the SSM endpoints and the database"
  }

  tags = merge(local.tags, { Name = "${local.prefix}-bastion" })

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_instance" "bastion" {
  ami           = data.aws_ami.bastion.id
  instance_type = "t4g.nano"

  subnet_id                   = var.public_subnet_ids[0]
  vpc_security_group_ids      = [aws_security_group.bastion.id]
  associate_public_ip_address = true
  iam_instance_profile        = aws_iam_instance_profile.bastion.name

  metadata_options {
    http_tokens = "required" # IMDSv2
  }

  root_block_device {
    encrypted = true
  }

  tags = merge(local.tags, { Name = "${local.prefix}-bastion" })
}
