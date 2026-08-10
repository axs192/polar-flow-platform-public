# GitHub Actions OIDC federation - no long-lived AWS keys stored in GitHub.
#
# Single role (gha-deploy) - narrowed to Docker-image deploy only. This used
# to be two roles split by blast radius (gha-terraform-plan, read-only and
# assumable from any workflow run incl. PRs; gha-deploy, write, for both
# `terraform apply` and per-service image deploys), backing terraform-plan.yml
# and terraform-apply.yml. Both workflows were removed in favor of running
# `terraform apply` manually, locally, from the polar-app-prod CLI profile
# after PR review - a solo-repo simplification, and it also permanently
# retires the risk class behind the hung-apply incident in
# docs/architecture.md's Review 4 (apply never runs unattended in CI again).
# gha-terraform-plan had no remaining caller once terraform-plan.yml was
# deleted, so it's gone entirely. gha-deploy's permissions are pruned down to
# only what deploy-service.yml actually calls (ECR push + Lambda code
# update) - the broad terraform-apply-era grants (DynamoDB/SQS/S3 table and
# queue admin, IAM role management, API Gateway, Terraform state access,
# etc.) are gone since nothing in CI needs them anymore. gha-deploy is still
# scoped to only be assumable from a workflow run on refs/heads/main - never
# from a pull_request event - so a PR alone, even a malicious one, can never
# reach it. Triggered only by workflow_dispatch (manual), never automatically
# on merge - see deploy-service.yml for the reasoning.

resource "aws_iam_openid_connect_provider" "github_actions" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
  # thumbprint_list deliberately omitted, not set to [] - AWS validates
  # GitHub's OIDC cert against its own trusted root CAs and auto-populates
  # this from the live cert (terraform-provider-aws#32480), but only when
  # the argument is absent entirely. Setting it to an explicit empty list
  # fights that auto-population on every subsequent plan (confirmed: caused
  # a spurious in-place-update diff, cascading into every resource whose
  # policy references this provider's ARN).
}

# --- gha-deploy: write access for per-service Docker image deploys ---
#
# Manual-trigger only (workflow_dispatch), never on a pull_request event or
# automatically on merge - decided explicitly rather than assumed, given
# every real apply in this repo so far has gone through an explicit human
# go-ahead. This role's trust policy is the enforcement mechanism for that:
# scoped to only be assumable from a workflow run on refs/heads/main, so a
# PR - even a malicious one - can never reach it regardless of what the
# workflow file itself does.

locals {
  ecr_deploy_repo_names = ["exercise-etl", "health-sync", "exercise-insights"]
}

data "aws_iam_policy_document" "gha_deploy_assume_role" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github_actions.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    # GitHub embeds numeric IDs (not just the human-readable owner/repo
    # names) in this claim once a repo/org has ever been renamed - if the
    # literal string below stops matching, re-derive the real value from
    # CloudTrail (a denied AssumeRoleWithWebIdentity call logs the exact
    # sub claim GitHub actually sent) rather than guessing the format.
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:YOUR_GITHUB_ORG/YOUR_REPO_NAME:ref:refs/heads/main"]
    }
  }
}

resource "aws_iam_role" "gha_deploy" {
  name               = "gha-deploy"
  assume_role_policy = data.aws_iam_policy_document.gha_deploy_assume_role.json
}

# Scoped to exactly what deploy-service.yml calls: `docker login` (ECRAuth),
# `docker push` (ECRImagePush), `aws lambda update-function-code` +
# `aws lambda wait function-updated` (LambdaCodeUpdate), and the
# `aws sts get-caller-identity` it uses to build the ECR registry URL
# (CallerIdentity). Everything this role used to also carry for
# `terraform apply` itself (DynamoDB/SQS/S3/secret/API Gateway/IAM
# role/Terraform-state management) is gone - see this file's top comment.
data "aws_iam_policy_document" "gha_deploy_permissions" {
  statement {
    sid       = "ECRImagePush"
    actions   = ["ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage", "ecr:BatchCheckLayerAvailability", "ecr:PutImage", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart", "ecr:CompleteLayerUpload"]
    resources = [for name in local.ecr_deploy_repo_names : "arn:aws:ecr:${var.aws_region}:${data.aws_caller_identity.current.account_id}:repository/${name}"]
  }

  statement {
    sid       = "ECRAuth"
    actions   = ["ecr:GetAuthorizationToken"] # this action alone doesn't support resource-level scoping - must be "*"
    resources = ["*"]
  }

  statement {
    sid       = "LambdaCodeUpdate"
    actions   = ["lambda:UpdateFunctionCode", "lambda:GetFunction"] # GetFunction is what `aws lambda wait function-updated` polls
    resources = [for name in local.ecr_deploy_repo_names : "arn:aws:lambda:${var.aws_region}:${data.aws_caller_identity.current.account_id}:function:${name}"]
  }

  statement {
    sid       = "CallerIdentity"
    actions   = ["sts:GetCallerIdentity"] # doesn't support resource-level scoping - must be "*"
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "gha_deploy" {
  name   = "deploy"
  role   = aws_iam_role.gha_deploy.id
  policy = data.aws_iam_policy_document.gha_deploy_permissions.json
}

output "gha_deploy_role_arn" {
  description = "Set as the AWS_DEPLOY_ROLE_ARN repo variable (gh variable set) - never commit this literal ARN, it contains the real account id."
  value       = aws_iam_role.gha_deploy.arn
}
