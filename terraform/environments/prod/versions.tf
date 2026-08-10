terraform {
  required_version = ">= 1.9"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # Bucket/table names pasted literally from `terraform output` in
  # terraform/bootstrap - backend blocks can't reference variables or data
  # sources. Both are opaque/random, not derived from the account ID, so
  # safe to commit (see terraform/bootstrap/README.md).
  #
  # profile is likewise a literal, not var.aws_profile, for the same reason
  # (backend blocks can't reference variables) - without it this silently
  # falls back to whatever AWS_PROFILE/default credentials are active, which
  # is a different AWS account entirely and 403s trying to reach this state
  # bucket. Not just a hypothetical: hit exactly this 403 while validating.
  backend "s3" {
    bucket         = "polar-flow-platform-tfstate-fda6588e"
    key            = "environments/prod/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "polar-flow-platform-tfstate-lock"
    encrypt        = true
    profile        = "polar-app-prod"
  }
}
