terraform {
  required_version = ">= 1.9"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # Deliberately local state for this config only: it creates the S3
  # bucket + DynamoDB table that every other Terraform config in this repo
  # uses as its remote backend, so it can't depend on that backend itself
  # (chicken-and-egg). Applied once per new environment, then left alone.
  backend "local" {
    path = "terraform.tfstate"
  }
}
