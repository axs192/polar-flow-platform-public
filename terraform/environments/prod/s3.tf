# Same hardening posture as terraform/bootstrap's state bucket: versioned,
# SSE-S3 encrypted, all public access blocked, ACLs disabled entirely.
# Random suffix for global uniqueness (S3 bucket names are global), not the
# account ID - keeps the account ID out of anything committed or output.

resource "random_id" "health_metrics_bucket_suffix" {
  byte_length = 4
}

resource "aws_s3_bucket" "health_metrics" {
  bucket = "${var.project_name}-health-metrics-${random_id.health_metrics_bucket_suffix.hex}"

  lifecycle {
    # Bootstrap's own state bucket already has this - the prod data buckets
    # didn't, which is exactly what let a hung terraform-apply.yml run get
    # as far as it did on 2026-08-06 (it silently computed a plan to
    # destroy+recreate this bucket before hanging). With this set, that
    # same plan would have hard-errored at apply time instead.
    prevent_destroy = true
  }
}

resource "random_id" "prompts_bucket_suffix" {
  byte_length = 4
}

resource "aws_s3_bucket" "prompts" {
  bucket = "${var.project_name}-prompts-${random_id.prompts_bucket_suffix.hex}"

  lifecycle {
    prevent_destroy = true # see health_metrics above for why
  }
}

locals {
  hardened_buckets = {
    health_metrics = aws_s3_bucket.health_metrics.id
    prompts        = aws_s3_bucket.prompts.id
  }
}

resource "aws_s3_bucket_versioning" "hardened" {
  for_each = local.hardened_buckets
  bucket   = each.value
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "hardened" {
  for_each = local.hardened_buckets
  bucket   = each.value
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "hardened" {
  for_each = local.hardened_buckets
  bucket   = each.value

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "hardened" {
  for_each = local.hardened_buckets
  bucket   = each.value
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# Versioning is Enabled but nothing was pruning old versions - bootstrap's
# state bucket already has this same rule (see terraform/bootstrap/main.tf).
# Without it, every overwritten object (routine for health_metrics' daily
# backfill) leaves a noncurrent version around forever, leaking storage
# cost with no benefit once it's old enough that no one would restore it.
resource "aws_s3_bucket_lifecycle_configuration" "hardened" {
  for_each = local.hardened_buckets
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
