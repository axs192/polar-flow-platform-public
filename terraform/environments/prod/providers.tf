provider "aws" {
  profile = var.aws_profile
  region  = var.aws_region

  default_tags {
    tags = {
      Project     = var.project_name
      Environment = "prod"
      ManagedBy   = "terraform/environments/prod"
    }
  }
}

# Account ID is never hardcoded (see CLAUDE.md) - resolved dynamically here
# wherever a policy/ARN needs it.
data "aws_caller_identity" "current" {}
