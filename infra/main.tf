# Terraform settings, the AWS provider, and the budget alert.
# Each other .tf file in this folder covers one part of the system:
#   database.tf  - DynamoDB table
#   backend.tf   - Lambda functions and their permissions
#   api.tf       - API Gateway (the public HTTPS API)
#   auth.tf      - Cognito (login)
#   frontend.tf  - S3 + CloudFront (the web app)
#   schedules.tf - evening reminder and weekly summary emails

terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }
}

provider "aws" {
  region = var.aws_region

  # Every resource gets this tag, so Cost Explorer can show this project's cost.
  default_tags {
    tags = {
      Project = var.project_name
    }
  }
}

data "aws_caller_identity" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  app_url    = "https://${aws_cloudfront_distribution.frontend.domain_name}"
}

# Emails you if spending gets anywhere near your limit.
resource "aws_budgets_budget" "monthly" {
  name         = "${var.project_name}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  # Count spending BEFORE credits are applied, so you can see how fast
  # credits are being used instead of a misleading $0.
  cost_types {
    include_credit = false
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 50
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alert_email]
  }
}
