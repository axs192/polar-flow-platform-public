variable "table_name" {
  description = "DynamoDB table name."
  type        = string
}

variable "hash_key" {
  description = "Partition key attribute name."
  type        = string
  default     = "uid"
}

variable "range_key" {
  description = "Sort key attribute name."
  type        = string
  default     = "date"
}

variable "tags" {
  description = "Extra tags to merge with the provider's default_tags."
  type        = map(string)
  default     = {}
}
