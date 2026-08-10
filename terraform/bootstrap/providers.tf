provider "aws" {
  profile = var.aws_profile
  region  = var.aws_region

  default_tags {
    tags = {
      Project   = var.project_name
      ManagedBy = "terraform/bootstrap"
    }
  }
}

# Account ID is never hardcoded anywhere in this repo (see CLAUDE.md) - it's
# always resolved dynamically at apply time via this data source, so the
# .tf source contains no real AWS account ID at all.
data "aws_caller_identity" "current" {}
