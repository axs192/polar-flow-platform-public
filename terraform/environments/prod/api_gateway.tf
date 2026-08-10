resource "aws_api_gateway_rest_api" "this" {
  name = var.project_name
}

# --- POST /webhook -> webhook-authenticator ---

resource "aws_api_gateway_resource" "webhook" {
  rest_api_id = aws_api_gateway_rest_api.this.id
  parent_id   = aws_api_gateway_rest_api.this.root_resource_id
  path_part   = "webhook"
}

resource "aws_api_gateway_method" "webhook_post" {
  rest_api_id   = aws_api_gateway_rest_api.this.id
  resource_id   = aws_api_gateway_resource.webhook.id
  http_method   = "POST"
  authorization = "NONE" # Polar signs the body (HMAC), verified inside the Lambda itself
}

resource "aws_api_gateway_integration" "webhook_post" {
  rest_api_id             = aws_api_gateway_rest_api.this.id
  resource_id             = aws_api_gateway_resource.webhook.id
  http_method             = aws_api_gateway_method.webhook_post.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = module.webhook_authenticator.invoke_arn
}

# --- /messenger: GET (Meta verify handshake) -> whatsapp-webhook-verify, POST (inbound message) -> whatsapp-inbound ---
# One callback URL for both, per Meta's actual webhook convention - this is
# also what fixes MetaAuth/whatsapp-webhook-verify being orphaned in the old
# account (no route existed there at all).

resource "aws_api_gateway_resource" "messenger" {
  rest_api_id = aws_api_gateway_rest_api.this.id
  parent_id   = aws_api_gateway_rest_api.this.root_resource_id
  path_part   = "messenger"
}

resource "aws_api_gateway_method" "messenger_get" {
  rest_api_id   = aws_api_gateway_rest_api.this.id
  resource_id   = aws_api_gateway_resource.messenger.id
  http_method   = "GET"
  authorization = "NONE" # Meta's hub.verify_token is checked inside the Lambda itself
}

resource "aws_api_gateway_integration" "messenger_get" {
  rest_api_id             = aws_api_gateway_rest_api.this.id
  resource_id             = aws_api_gateway_resource.messenger.id
  http_method             = aws_api_gateway_method.messenger_get.http_method
  integration_http_method = "POST" # Lambda proxy integrations always call the Lambda via POST, regardless of the client's HTTP method
  type                    = "AWS_PROXY"
  uri                     = module.whatsapp_webhook_verify.invoke_arn
}

resource "aws_api_gateway_method" "messenger_post" {
  rest_api_id   = aws_api_gateway_rest_api.this.id
  resource_id   = aws_api_gateway_resource.messenger.id
  http_method   = "POST"
  authorization = "NONE" # Meta's X-Hub-Signature-256 is verified inside the Lambda itself
}

resource "aws_api_gateway_integration" "messenger_post" {
  rest_api_id             = aws_api_gateway_rest_api.this.id
  resource_id             = aws_api_gateway_resource.messenger.id
  http_method             = aws_api_gateway_method.messenger_post.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = module.whatsapp_inbound.invoke_arn
}

resource "aws_api_gateway_deployment" "this" {
  rest_api_id = aws_api_gateway_rest_api.this.id

  triggers = {
    redeployment = sha1(jsonencode([
      aws_api_gateway_resource.webhook.id,
      aws_api_gateway_method.webhook_post.id,
      aws_api_gateway_integration.webhook_post.id,
      aws_api_gateway_resource.messenger.id,
      aws_api_gateway_method.messenger_get.id,
      aws_api_gateway_integration.messenger_get.id,
      aws_api_gateway_method.messenger_post.id,
      aws_api_gateway_integration.messenger_post.id,
    ]))
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_api_gateway_stage" "prod" {
  # Named "prod", not "development" like the old account - see
  # docs/architecture.md issue #12 (stage naming didn't match reality).
  stage_name    = "prod"
  rest_api_id   = aws_api_gateway_rest_api.this.id
  deployment_id = aws_api_gateway_deployment.this.id
}
