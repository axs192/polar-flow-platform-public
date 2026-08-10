locals {
  # "orders.fifo" -> "orders-dlq.fifo" - keep the .fifo suffix at the end,
  # DLQs for FIFO source queues must themselves be FIFO queues.
  dlq_name = "${trimsuffix(var.queue_name, ".fifo")}-dlq.fifo"
}

resource "aws_sqs_queue" "dlq" {
  name                        = local.dlq_name
  fifo_queue                  = true
  content_based_deduplication = var.content_based_deduplication
  # DLQ messages should outlive the source queue's own retention so there's
  # time to notice+investigate the CloudWatch alarm before they expire.
  message_retention_seconds = 1209600 # 14 days, SQS's max

  tags = var.tags
}

resource "aws_sqs_queue" "this" {
  name                        = var.queue_name
  fifo_queue                  = true
  content_based_deduplication = var.content_based_deduplication
  message_retention_seconds   = var.message_retention_seconds
  visibility_timeout_seconds  = var.visibility_timeout_seconds

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = var.max_receive_count
  })

  tags = var.tags
}
