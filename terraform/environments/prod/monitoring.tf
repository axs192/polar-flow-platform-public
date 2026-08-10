# Minimal, not gold-plated (see docs/architecture.md's Observability
# section) - one cheap, high-value thing: alert on a DLQ message, and on
# repeated webhook signature failures. Both were previously invisible.

resource "aws_sns_topic" "alerts" {
  name = "${var.project_name}-alerts"
  # AWS-managed key, not a customer-managed one - free (see
  # docs/architecture.md's Observability section on deliberately skipping a
  # CMK), and closes a real Trivy HIGH finding (AWS-0095) that a CMK
  # decision doesn't actually cover - unencrypted-at-rest and
  # customer-managed-key-or-not are two different questions.
  kms_master_key_id = "alias/aws/sns"
}

resource "aws_sns_topic_subscription" "alerts_email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

locals {
  dlqs = {
    polar_webhook    = module.polar_webhook_queue.dlq_name
    exercise_message = module.exercise_message_queue.dlq_name
    user_query       = module.user_query_queue.dlq_name
  }
}

resource "aws_cloudwatch_metric_alarm" "dlq_has_messages" {
  for_each            = local.dlqs
  alarm_name          = "${each.value}-has-messages"
  alarm_description   = "A message landed in ${each.value} - something failed all ${3} delivery attempts and is not being retried automatically."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = each.value }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
}

# Repeated webhook signature failures - both webhook-authenticator and
# whatsapp-inbound log the exact same string on a bad signature (see
# lambda_handler.py in each). whatsapp-webhook-verify (the Meta GET
# handshake) isn't included - it's low-volume/low-risk by comparison.
locals {
  signature_verifying_functions = {
    webhook_authenticator = module.webhook_authenticator.log_group_name
    whatsapp_inbound      = module.whatsapp_inbound.log_group_name
  }
}

resource "aws_cloudwatch_log_metric_filter" "signature_failure" {
  for_each       = local.signature_verifying_functions
  name           = "${each.key}-signature-failures"
  log_group_name = each.value
  pattern        = "\"Unauthorized: signature verification failed\""

  metric_transformation {
    name      = "${each.key}SignatureFailures"
    namespace = "${var.project_name}/security"
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "signature_failure" {
  for_each = local.signature_verifying_functions

  alarm_name          = "${each.key}-repeated-signature-failures"
  alarm_description   = "${each.key} rejected 5+ webhook signatures in 5 minutes - could be a misconfigured secret, or someone probing the endpoint."
  namespace           = "${var.project_name}/security"
  metric_name         = "${each.key}SignatureFailures"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 5
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]

  depends_on = [aws_cloudwatch_log_metric_filter.signature_failure]
}
