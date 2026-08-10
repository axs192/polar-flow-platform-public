output "state_bucket_name" {
  description = "Paste this literally into environments/*/versions.tf's backend \"s3\" block (bucket = ...). Backend blocks can't reference variables/data sources, so this has to be a hardcoded string downstream - but it's an opaque random name, not the account ID, so that's fine to commit."
  value       = aws_s3_bucket.terraform_state.bucket
}

output "lock_table_name" {
  description = "Paste this literally into environments/*/versions.tf's backend \"s3\" block (dynamodb_table = ...)."
  value       = aws_dynamodb_table.terraform_lock.name
}

output "region" {
  value = var.aws_region
}
