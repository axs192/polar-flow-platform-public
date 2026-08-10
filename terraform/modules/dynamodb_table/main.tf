# uid/date as String: matches every service's actual usage today - uid is
# always a Polar member-id-shaped string, date is always a formatted date
# string (e.g. "2026/01/01" or an ISO date), never a native Number/epoch.
resource "aws_dynamodb_table" "this" {
  name         = var.table_name
  billing_mode = "PAY_PER_REQUEST" # no fixed monthly cost at personal-scale traffic
  hash_key     = var.hash_key
  range_key    = var.range_key

  attribute {
    name = var.hash_key
    type = "S"
  }

  attribute {
    name = var.range_key
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  # Stronger than Terraform's own prevent_destroy (see s3.tf's equivalent
  # fix) - this is enforced by the DynamoDB API itself, so it also blocks a
  # console/CLI delete, not just terraform apply/destroy. Every real table
  # this module creates holds actual application data, not throwaway state.
  deletion_protection_enabled = true

  tags = var.tags
}
