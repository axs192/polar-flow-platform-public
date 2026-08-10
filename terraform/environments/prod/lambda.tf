locals {
  services_root = "${path.module}/../../../services"
}

# --- webhook-authenticator: POST /webhook -> dispatches to polar-webhook.fifo (SLEEP) / exercise-message.fifo (EXERCISE) ---

data "aws_iam_policy_document" "webhook_authenticator" {
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.app.arn]
  }
  statement {
    actions = ["sqs:SendMessage"]
    resources = [
      module.polar_webhook_queue.queue_arn,
      module.exercise_message_queue.queue_arn,
    ]
  }
}

module "webhook_authenticator" {
  source                 = "../../modules/lambda_function"
  function_name          = "webhook-authenticator"
  description            = "Polar Flow webhook ingress: verifies HMAC signature, dispatches by event type."
  package_type           = "Zip"
  source_dir             = "${local.services_root}/webhook-authenticator/src"
  handler                = "app.lambda_handler.lambda_handler"
  runtime                = "python3.12"
  additional_policy_json = data.aws_iam_policy_document.webhook_authenticator.json
  environment_variables = {
    AWS_APP_SECRET_NAME    = aws_secretsmanager_secret.app.name
    AWS_APP_REGION         = var.aws_region
    SQS_QUEUE_URL          = module.polar_webhook_queue.queue_url
    SQS_EXERCISE_QUEUE_URL = module.exercise_message_queue.queue_url
  }
}

resource "aws_lambda_permission" "webhook_authenticator_apigw" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = module.webhook_authenticator.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.this.execution_arn}/*/POST/webhook"
}

# --- whatsapp-webhook-verify: GET /messenger -> Meta's handshake (hub.mode/hub.verify_token/hub.challenge) ---

data "aws_iam_policy_document" "whatsapp_webhook_verify" {
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.app.arn]
  }
}

module "whatsapp_webhook_verify" {
  source                 = "../../modules/lambda_function"
  function_name          = "whatsapp-webhook-verify"
  description            = "Meta WhatsApp webhook verification handshake (GET /messenger)."
  package_type           = "Zip"
  source_dir             = "${local.services_root}/whatsapp-webhook-verify/src"
  handler                = "app.lambda_handler.lambda_handler"
  runtime                = "python3.14"
  additional_policy_json = data.aws_iam_policy_document.whatsapp_webhook_verify.json
  environment_variables = {
    AWS_APP_SECRET_NAME = aws_secretsmanager_secret.app.name
    AWS_APP_REGION      = var.aws_region
  }
}

resource "aws_lambda_permission" "whatsapp_webhook_verify_apigw" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = module.whatsapp_webhook_verify.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.this.execution_arn}/*/GET/messenger"
}

# --- whatsapp-inbound: POST /messenger -> forwards inbound message text to user-query.fifo ---

data "aws_iam_policy_document" "whatsapp_inbound" {
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.app.arn]
  }
  statement {
    actions   = ["sqs:SendMessage"]
    resources = [module.user_query_queue.queue_arn]
  }
}

module "whatsapp_inbound" {
  source                 = "../../modules/lambda_function"
  function_name          = "whatsapp-inbound"
  description            = "Inbound WhatsApp messages (POST /messenger): verifies signature, forwards to user-query.fifo."
  package_type           = "Zip"
  source_dir             = "${local.services_root}/whatsapp-inbound/src"
  handler                = "app.lambda_handler.lambda_handler"
  runtime                = "python3.14"
  additional_policy_json = data.aws_iam_policy_document.whatsapp_inbound.json
  environment_variables = {
    AWS_APP_SECRET_NAME      = aws_secretsmanager_secret.app.name
    AWS_APP_REGION           = var.aws_region
    SQS_USER_QUERY_QUEUE_URL = module.user_query_queue.queue_url
  }
}

resource "aws_lambda_permission" "whatsapp_inbound_apigw" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = module.whatsapp_inbound.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.this.execution_arn}/*/POST/messenger"
}

# --- exercise-etl: SQS-triggered (exercise-message.fifo) -> writes exercise_data ---

data "aws_iam_policy_document" "exercise_etl" {
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.app.arn]
  }
  statement {
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
    resources = [module.exercise_message_queue.queue_arn]
  }
  statement {
    actions   = ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:DescribeTable"]
    resources = [module.exercise_data_table.arn]
  }
}

module "exercise_etl" {
  source                 = "../../modules/lambda_function"
  function_name          = "exercise-etl"
  description            = "Fetches exercise JSON + .fit from Accesslink, computes derived metrics, writes exercise_data."
  package_type           = "Image"
  image_uri              = var.exercise_etl_image_uri
  timeout                = 60
  memory_size            = 512
  additional_policy_json = data.aws_iam_policy_document.exercise_etl.json
  create_sqs_trigger     = true
  sqs_trigger_arn        = module.exercise_message_queue.queue_arn
  environment_variables = {
    AWS_APP_SECRET_NAME = aws_secretsmanager_secret.app.name
    AWS_APP_REGION      = var.aws_region
    TABLE_NAME          = module.exercise_data_table.name
    FIT_FILE            = "/tmp/exercise.fit"
  }
}

# --- health-sync: SQS-triggered (polar-webhook.fifo, on SLEEP events) -> WhatsApp summary + backfills health_metrics/S3 ---

data "aws_iam_policy_document" "health_sync" {
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.app.arn]
  }
  statement {
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
    resources = [module.polar_webhook_queue.queue_arn]
  }
  statement {
    actions   = ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:Query"]
    resources = [module.health_metrics_table.arn]
  }
  statement {
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.health_metrics.arn}/*"]
  }
}

module "health_sync" {
  source                 = "../../modules/lambda_function"
  function_name          = "health-sync"
  description            = "Sends daily WhatsApp activity summary; backfills up to 10 days of health data."
  package_type           = "Image"
  image_uri              = var.health_sync_image_uri
  timeout                = 60
  memory_size            = 512
  additional_policy_json = data.aws_iam_policy_document.health_sync.json
  create_sqs_trigger     = true
  sqs_trigger_arn        = module.polar_webhook_queue.queue_arn
  environment_variables = {
    AWS_APP_SECRET_NAME = aws_secretsmanager_secret.app.name
    AWS_APP_REGION      = var.aws_region
    TABLE_NAME          = module.health_metrics_table.name
    BUCKET_NAME         = aws_s3_bucket.health_metrics.id
    FOLDER_PATH         = "prod_health_data"
    TO_MOBILE           = var.to_mobile_number
    FROM_MOBILE         = var.from_mobile_number
  }
}

# --- exercise-insights: SQS-triggered (user-query.fifo) -> reads exercise_data, calls OpenAI, replies over WhatsApp ---

data "aws_iam_policy_document" "exercise_insights" {
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.app.arn]
  }
  statement {
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
    resources = [module.user_query_queue.queue_arn]
  }
  statement {
    # Read-only: answer_question() only ever calls get_records_bt_dates()
    # (a Query). dynamo_extract also has an add_record()/put_item path, but
    # nothing in this service's real call path invokes it - not granted.
    actions   = ["dynamodb:Query", "dynamodb:GetItem"]
    resources = [module.exercise_data_table.arn]
  }
  statement {
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.prompts.arn}/*"]
  }
}

module "exercise_insights" {
  source                 = "../../modules/lambda_function"
  function_name          = "exercise-insights"
  description            = "Answers WhatsApp questions about exercise history via OpenAI, using the last 90 days of exercise_data."
  package_type           = "Image"
  image_uri              = var.exercise_insights_image_uri
  timeout                = 60
  memory_size            = 512
  additional_policy_json = data.aws_iam_policy_document.exercise_insights.json
  create_sqs_trigger     = true
  sqs_trigger_arn        = module.user_query_queue.queue_arn
  environment_variables = {
    AWS_APP_SECRET_NAME  = aws_secretsmanager_secret.app.name
    AWS_APP_REGION       = var.aws_region
    BUCKET_NAME          = aws_s3_bucket.prompts.id
    EXERCISE_PROMPT_PATH = "exercise_system_prompt.txt"
    HEALTH_PROMPT_PATH   = "health_system_prompt.txt"
    POLAR_USER_ID        = var.polar_user_id
    TO_MOBILE            = var.to_mobile_number
    FROM_MOBILE          = var.from_mobile_number
  }
}
