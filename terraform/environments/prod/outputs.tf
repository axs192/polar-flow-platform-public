output "api_base_url" {
  description = "Base invoke URL. Append /webhook or /messenger."
  value       = aws_api_gateway_stage.prod.invoke_url
}

output "ecr_repository_urls" {
  value = { for name, repo in aws_ecr_repository.this : name => repo.repository_url }
}

output "app_secret_name" {
  value = aws_secretsmanager_secret.app.name
}

output "app_secret_arn" {
  value = aws_secretsmanager_secret.app.arn
}

output "dynamodb_table_names" {
  value = {
    exercise_data  = module.exercise_data_table.name
    health_metrics = module.health_metrics_table.name
  }
}

output "sqs_queue_urls" {
  value = {
    polar_webhook    = module.polar_webhook_queue.queue_url
    exercise_message = module.exercise_message_queue.queue_url
    user_query       = module.user_query_queue.queue_url
  }
}

output "s3_bucket_names" {
  value = {
    health_metrics  = aws_s3_bucket.health_metrics.id
    prompts         = aws_s3_bucket.prompts.id
    web_app_context = aws_s3_bucket.web_app_context.id
  }
}

output "rpi_web_app_iam_user" {
  description = "Generate its access key out-of-band (see web_app.tf's comment) - never through Terraform."
  value       = aws_iam_user.rpi_web_app.name
}
