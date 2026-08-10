variable "aws_profile" {
  description = "Local AWS CLI profile to operate against. Not sensitive - just a name; real credentials/account resolution happen via ~/.aws/config, never hardcoded here."
  type        = string
  default     = "polar-app-prod"
}

variable "aws_region" {
  description = "Region to create the state backend in."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Used to name/tag the backend resources."
  type        = string
  default     = "polar-flow-platform"
}
