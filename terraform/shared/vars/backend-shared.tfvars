bucket = "tf-state-project-zeno"
# Unchanged deliberately: this state already tracks the live database, and
# repointing it would orphan every resource in it.
key     = "terraform/state/terraform.tfstate"
region  = "us-east-1"
encrypt = true
