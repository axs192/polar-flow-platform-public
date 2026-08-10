# Note on the random suffix below: S3 bucket names must be globally unique.
# The idiomatic shortcut is embedding the account ID, but that name becomes a
# literal string pasted into downstream backend "s3" blocks (backend config
# can't use variables/data sources) - which would put the real account ID
# into a committed file. Using an opaque random suffix instead avoids that
# entirely; the bucket name discloses nothing about which account it's in.
resource "random_id" "state_bucket_suffix" {
  byte_length = 4
}

resource "aws_s3_bucket" "terraform_state" {
  bucket = "${var.project_name}-tfstate-${random_id.state_bucket_suffix.hex}"

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id
  rule {
    apply_server_side_encryption_by_default {
      # SSE-S3 (AES256), not a customer-managed KMS key - state contents
      # here are infra config, not user data, and a CMK adds ~$1/month +
      # per-request cost for no meaningful benefit at this scale.
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id
  rule {
    object_ownership = "BucketOwnerEnforced" # disables ACLs entirely
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id
  rule {
    id     = "expire-noncurrent-state-versions"
    status = "Enabled"
    filter {} # applies to all objects in the bucket
    noncurrent_version_expiration {
      noncurrent_days = 90
    }
  }
}

resource "aws_dynamodb_table" "terraform_lock" {
  name         = "${var.project_name}-tfstate-lock"
  billing_mode = "PAY_PER_REQUEST" # no fixed monthly cost at this traffic
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }
}

# TODO once CI's OIDC role exists (later CI/CD phase): add a bucket policy
# restricting write access to that role specifically, per the hardening
# noted in docs/architecture.md. Not blocking today - public access block +
# BucketOwnerEnforced already prevent the meaningful risk (public exposure).
