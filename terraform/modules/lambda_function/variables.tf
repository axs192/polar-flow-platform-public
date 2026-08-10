variable "function_name" {
  type = string
}

variable "description" {
  type    = string
  default = ""
}

variable "package_type" {
  description = "\"Zip\" or \"Image\"."
  type        = string
  validation {
    condition     = contains(["Zip", "Image"], var.package_type)
    error_message = "package_type must be \"Zip\" or \"Image\"."
  }
}

# --- Zip-only ---
variable "source_dir" {
  description = "Directory to zip (Zip package type only). All 3 zip-based services here depend on nothing beyond boto3, which the Lambda Python runtime already provides, so a plain zip of src/ is a complete deployment artifact - no build/dependency step needed."
  type        = string
  default     = null
}

variable "handler" {
  description = "Required for Zip package type, e.g. \"app.lambda_handler.lambda_handler\". Note: source_dir is zipped by its *contents* (not the directory itself), so if source_dir is \".../src\", the zip root is \"src\"'s contents - the handler path must NOT include a leading \"src.\"."
  type        = string
  default     = null
}

variable "runtime" {
  description = "Required for Zip package type, e.g. \"python3.12\"."
  type        = string
  default     = null
}

# --- Image-only ---
variable "image_uri" {
  description = "Required for Image package type. The ECR repo must already contain this tag/digest before the first apply - Lambda validates the image exists at creation time, so there's an unavoidable manual bootstrap step (see environments/prod/README.md) before step 7's CI/CD can take over ongoing deploys."
  type        = string
  default     = null
}

# --- Common ---
variable "environment_variables" {
  type    = map(string)
  default = {}
}

variable "timeout" {
  type    = number
  default = 30
}

variable "memory_size" {
  type    = number
  default = 256
}

variable "log_retention_days" {
  type    = number
  default = 14
}

variable "additional_policy_json" {
  description = "Extra IAM policy document (JSON string, e.g. from data.aws_iam_policy_document.this.json) merged alongside the base CloudWatch Logs permissions this module always grants. Required - every Lambda here needs at least secretsmanager:GetSecretValue."
  type        = string
}

variable "create_sqs_trigger" {
  description = "Whether to wire an SQS event source mapping. A separate literal boolean, not inferred from sqs_trigger_arn being set - the ARN usually comes from a sibling queue created in the same apply and is unknown at plan time, which breaks a count/for_each keyed off its nullness."
  type        = bool
  default     = false
}

variable "sqs_trigger_arn" {
  description = "Required if create_sqs_trigger is true. The caller must also grant sqs:ReceiveMessage/DeleteMessage/GetQueueAttributes on this ARN via additional_policy_json - this module only creates the mapping, not the permissions."
  type        = string
  default     = null
}

variable "sqs_batch_size" {
  type    = number
  default = 1
}

variable "tags" {
  type    = map(string)
  default = {}
}
