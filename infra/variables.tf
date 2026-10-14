variable "aws_region" {
  description = "Your project's AWS region (shown in AWS Settings)"
  type        = string
  default     = "us-east-2"
}

variable "project_name" {
  description = "Prefix used in every resource name"
  type        = string
  default     = "fitness-tracker"
}

variable "alert_email" {
  description = "Your email: used for login, reminders, and budget alerts"
  type        = string
}

variable "monthly_budget_usd" {
  description = "Monthly spending limit for the budget alert"
  type        = number
  default     = 5
}

variable "timezone" {
  description = "Time zone for the scheduled emails, e.g. America/New_York"
  type        = string
  default     = "America/New_York"
}

variable "reminder_hour" {
  description = "Hour of the evening reminder email, 0-23 in your time zone"
  type        = number
  default     = 20
}

variable "usda_api_key" {
  description = "Free key from https://api.data.gov/signup/ (DEMO_KEY works for light testing)"
  type        = string
  default     = "DEMO_KEY"
  sensitive   = true
}

variable "bedrock_model_id" {
  description = "Bedrock model (or inference profile) used to read meal descriptions"
  type        = string
  default     = "us.amazon.nova-lite-v1:0"
}
