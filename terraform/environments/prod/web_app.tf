# Infra for app/polar_web_app (the AI running-coach web app) - NOT part of
# the Lambda/API Gateway/SQS pipeline above. This app runs on a Raspberry Pi
# at home (see docs/runbooks/raspberry-pi-web-app.md), not in this AWS
# account, so it needs its own long-lived credential rather than the
# OIDC-federated role cicd.tf sets up for GitHub Actions (OIDC only works
# for a caller that can present a GitHub Actions token, which the Pi can't).

resource "random_id" "web_app_context_bucket_suffix" {
  byte_length = 4
}

resource "aws_s3_bucket" "web_app_context" {
  bucket = "${var.project_name}-web-app-context-${random_id.web_app_context_bucket_suffix.hex}"

  lifecycle {
    prevent_destroy = true # see s3.tf's health_metrics bucket for why
  }
}

# Folded into the same hardened_buckets treatment as s3.tf's other buckets
# (versioning, SSE, public access block, ownership controls, noncurrent
# version expiration) - one user's profile.json/conversation.json per
# object, same low-volume-but-real-data shape as the other two buckets.
locals {
  web_app_hardened_buckets = {
    web_app_context = aws_s3_bucket.web_app_context.id
  }
}

resource "aws_s3_bucket_versioning" "web_app_hardened" {
  for_each = local.web_app_hardened_buckets
  bucket   = each.value
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "web_app_hardened" {
  for_each = local.web_app_hardened_buckets
  bucket   = each.value
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "web_app_hardened" {
  for_each = local.web_app_hardened_buckets
  bucket   = each.value

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "web_app_hardened" {
  for_each = local.web_app_hardened_buckets
  bucket   = each.value
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "web_app_hardened" {
  for_each = local.web_app_hardened_buckets
  bucket   = each.value
  rule {
    id     = "expire-noncurrent-versions"
    status = "Enabled"
    filter {} # applies to all objects in the bucket
    noncurrent_version_expiration {
      noncurrent_days = 90
    }
  }
}

# --- rpi-web-app: least-privilege IAM user for the Pi ---
#
# Deliberately an IAM user, not a role - the Pi is a physical device outside
# any AWS trust boundary Terraform can federate against (no OIDC, no
# instance profile), so a long-lived credential is the only option here.
# Scoped to exactly the two things app/polar_web_app's own code calls, per
# its README/.env.example and docs/runbooks/raspberry-pi-web-app.md:
# dynamodb:Query/GetItem on exercise_data (via
# exercise_insights.core.get_exercise_metrics) and s3:GetObject/PutObject on
# this bucket (via src/context_store.py). Nothing broader - no table/bucket
# admin, no other table, no other bucket.
#
# Matches secrets.tf's existing posture: Terraform creates the identity and
# its policy, but never the actual credential material. Generate the access
# key out-of-band after apply:
#   aws iam create-access-key --user-name rpi-web-app --profile polar-app-prod
# and paste the result straight into the Pi's own .env - never into a .tf
# file, Terraform state (an access key resource would put the secret key
# there in plaintext), or this repo.
resource "aws_iam_user" "rpi_web_app" {
  name = "rpi-web-app"
}

data "aws_iam_policy_document" "rpi_web_app" {
  statement {
    sid = "ExerciseDataReadOnly"
    # DescribeTable looks unused reading get_exercise_metrics's own code, but
    # exercise_insights.core.extract.dynamo_extract.__init__ always calls
    # self.exists(table) -> table.load(), and boto3's DynamoDB Table.load()
    # always issues a real DescribeTable call - on every single invocation,
    # not just once. Same underlying pattern that broke
    # exercise-etl-lambda-role before (docs/architecture.md step 8, item 9).
    # Confirmed live (2026-08-07): AccessDeniedException without this.
    actions   = ["dynamodb:Query", "dynamodb:GetItem", "dynamodb:DescribeTable"]
    resources = [module.exercise_data_table.arn]
  }

  statement {
    sid       = "ContextBucketReadWrite"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${aws_s3_bucket.web_app_context.arn}/*"]
  }

  # Without this, GetObject on a key that doesn't exist yet (every brand-new
  # user's first-ever profile.json/conversation.json lookup) returns 403
  # AccessDenied instead of 404 NoSuchKey - S3 won't tell a caller "not
  # found" vs "forbidden" unless they can also list the bucket, to stop
  # permission-less enumeration of key existence. context_store.py only
  # catches NoSuchKey, so that AccessDenied propagated unhandled - confirmed
  # live (2026-08-07), not caught by moto's tests, which don't reproduce
  # this real-AWS-specific behavior. ListBucket is a bucket-level action
  # (unlike GetObject/PutObject above), so it takes the bucket ARN itself,
  # not the `/*` object-level ARN.
  statement {
    sid       = "ContextBucketList"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.web_app_context.arn]
  }
}

resource "aws_iam_user_policy" "rpi_web_app" {
  name   = "rpi-web-app-least-privilege"
  user   = aws_iam_user.rpi_web_app.name
  policy = data.aws_iam_policy_document.rpi_web_app.json
}
