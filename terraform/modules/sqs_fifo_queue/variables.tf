variable "queue_name" {
  description = "Queue name, must end in \".fifo\"."
  type        = string

  validation {
    condition     = endswith(var.queue_name, ".fifo")
    error_message = "FIFO queue names must end in \".fifo\"."
  }
}

variable "content_based_deduplication" {
  description = "Every producer in this repo (webhook-authenticator, whatsapp-inbound) always passes an explicit MessageDeduplicationId on send_message, so content-based dedup would be redundant, not complementary - default false."
  type        = bool
  default     = false
}

variable "message_retention_seconds" {
  description = "Matches the old account's 24h retention on all 3 queues."
  type        = number
  default     = 86400
}

variable "max_receive_count" {
  description = "Deliveries before a message moves to the DLQ."
  type        = number
  default     = 3
}

variable "visibility_timeout_seconds" {
  description = "AWS requires this to be >= the consuming Lambda's timeout, and recommends >= 6x it so an in-flight retry has room to run. Every queue here defaults to matching an SQS-triggered Lambda, so the default is set for that; queues without an SQS trigger are unaffected by this value."
  type        = number
  default     = 30
}

variable "tags" {
  description = "Extra tags to merge with the provider's default_tags."
  type        = map(string)
  default     = {}
}
