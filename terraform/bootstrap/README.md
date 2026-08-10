# Terraform bootstrap

Creates the S3 bucket + DynamoDB table that every other Terraform config in this repo uses as its remote state backend. This one config intentionally uses **local** state (`terraform.tfstate`, gitignored) since it can't depend on the backend it's creating.

Run once per new environment:

```sh
cd terraform/bootstrap
terraform init
terraform apply
terraform output
```

Then paste the two outputs (`state_bucket_name`, `lock_table_name`) as literals into the relevant `environments/*/versions.tf`'s `backend "s3"` block — backend blocks can't reference variables or data sources, so this has to be a manual, one-time copy. This is safe to commit: the bucket name is an opaque random string (`polar-flow-platform-tfstate-<random hex>`), not derived from or containing the AWS account ID.

After that, this directory is rarely touched again — it's infrastructure for the infrastructure, not something you `apply` repeatedly.
