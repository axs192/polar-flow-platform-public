# polar-webhook.fifo: webhook-authenticator (SLEEP events) -> health-sync
module "polar_webhook_queue" {
  source                     = "../../modules/sqs_fifo_queue"
  queue_name                 = "polar-webhook.fifo"
  visibility_timeout_seconds = 360 # 6x health-sync's 60s Lambda timeout
}

# exercise-message.fifo: webhook-authenticator (EXERCISE events) -> exercise-etl
module "exercise_message_queue" {
  source                     = "../../modules/sqs_fifo_queue"
  queue_name                 = "exercise-message.fifo"
  visibility_timeout_seconds = 360 # 6x exercise-etl's 60s Lambda timeout
}

# user-query.fifo: whatsapp-inbound -> exercise-insights. Named to match the
# already-renamed SQS_USER_QUERY_QUEUE_URL env var (see whatsapp-inbound's
# README - the old deployed code's var name/queue purpose didn't match).
module "user_query_queue" {
  source                     = "../../modules/sqs_fifo_queue"
  queue_name                 = "user-query.fifo"
  visibility_timeout_seconds = 360 # 6x exercise-insights' 60s Lambda timeout
}
