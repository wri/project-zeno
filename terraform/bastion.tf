# Bastion for reaching the database from a laptop. The database is private, so
# this is the way in: SSM Session Manager port-forwards through it.
#
#   aws ssm start-session --target $(terraform output -raw bastion_instance_id) \
#     --document-name AWS-StartPortForwardingSessionToRemoteHost \
#     --parameters host=$(terraform output -raw db_address),portNumber=5432,localPortNumber=5432
#
# then connect to localhost:5432.
#
# It has a public IP but NO inbound rules and no key pair: the SSM agent dials
# out to AWS and the session is brokered back down that connection, so nothing
# is listening for inbound traffic. Access is authorized by IAM, and sessions
# are logged to CloudTrail. The public IP exists only so the agent can reach the
# SSM endpoints -- this VPC has no NAT gateway, and a private subnet would
# otherwise need three interface endpoints at roughly $22/month.
#
# Deliberately no key_name: with a key pair present people reach for SSH, which
# would mean opening port 22 and undoing the above.

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
  description = "Security group for the evals bastion"

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
