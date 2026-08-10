variable "aws_profile" {
  description = "Local AWS CLI profile to operate against."
  type        = string
  default     = "polar-app-prod"
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "project_name" {
  type    = string
  default = "polar-flow-platform"
}

variable "alert_email" {
  description = "Subscribed to the SNS topic that DLQ/signature-failure alarms publish to. Passed as a variable, not hardcoded, since an email address is personal information - set it in a gitignored terraform.tfvars (see README)."
  type        = string
}

variable "exercise_etl_image_uri" {
  description = "ECR image URI (repo:tag or repo@digest) for exercise-etl. Must already exist in ECR before the first apply - see README's bootstrap step."
  type        = string
}

variable "health_sync_image_uri" {
  description = "ECR image URI for health-sync. Must already exist in ECR before the first apply."
  type        = string
}

variable "exercise_insights_image_uri" {
  description = "ECR image URI for exercise-insights. Must already exist in ECR before the first apply."
  type        = string
}

variable "polar_user_id" {
  description = "The Polar user id (\"polar-user-id\"/\"x_user_id\") exercise-insights reads exercise_data for. Only known after a real user has been onboarded via polar-onboarding's authorize+register commands - see the README's bootstrap order. Defaults to empty so the first apply (before any user exists) still succeeds; exercise-insights just has nothing to answer questions about until this is set and re-applied."
  type        = string
  default     = ""
}

variable "to_mobile_number" {
  description = "The personal WhatsApp number (E.164, e.g. +15551234567) that health-sync's daily summary and exercise-insights' Q&A replies get sent to. Read as a plain Lambda env var (TO_MOBILE) by both services' push_notification code - not a Secrets Manager key. No default: both Lambdas raise on a missing env var at send time, so this must be supplied before the final apply."
  type        = string
}

variable "from_mobile_number" {
  description = "Meta's WhatsApp Business phone number ID (not a phone number itself - the numeric ID Meta assigns the sending number in the WhatsApp Business dashboard), used as the 'from' side of the Graph API send call. Read as a plain Lambda env var (FROM_MOBILE) by both services' push_notification code - not a Secrets Manager key. No default: both Lambdas raise on a missing env var at send time, so this must be supplied before the final apply."
  type        = string
}
