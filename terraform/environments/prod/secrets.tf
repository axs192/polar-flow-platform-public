# One shared secret, matching today's real production model exactly (see
# docs/architecture.md's Cost Considerations + Testing strategy sections) -
# every service's config_loader() reads exactly one secret by name, with no
# support for merging multiple, so splitting by integration would need a
# code change this step doesn't make. Every service's own README documents
# which keys it reads.
#
# Deliberately no aws_secretsmanager_secret_version here: this resource
# only creates the empty secret container. Populating/rotating the real
# values (client_id, client_secret, access_token, user_id, POLAR_WEBHOOK,
# META_AUTH, META_VERIFY_TOKEN, META_NOT_SEC, OPEN_AI_AUTH) happens
# out-of-band via the AWS CLI/console or polar-onboarding's
# `--store-secret-name` flag - never through Terraform, so real credentials
# never pass through a .tf file or get written into Terraform state.
resource "aws_secretsmanager_secret" "app" {
  name        = "${var.aws_profile}/app-secrets"
  description = "Shared credentials for all Polar Flow Platform Lambdas: Polar Accesslink creds, webhook signing secrets, WhatsApp send token, OpenAI key. See docs/architecture.md for the full key list."
}
