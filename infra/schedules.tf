# Scheduled emails, run by EventBridge Scheduler in YOUR time zone.

# SES only sends from (and, in sandbox mode, to) verified addresses.
# Terraform triggers a verification email: click the link in it.
resource "aws_ses_email_identity" "me" {
  email = var.alert_email
}

resource "aws_iam_role" "scheduler" {
  name = "${var.project_name}-scheduler-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "scheduler_invoke" {
  name = "invoke-jobs-lambda"
  role = aws_iam_role.scheduler.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "lambda:InvokeFunction"
      Resource = aws_lambda_function.jobs.arn
    }]
  })
}

resource "aws_scheduler_schedule" "evening_reminder" {
  name                         = "${var.project_name}-evening-reminder"
  schedule_expression          = "cron(0 ${var.reminder_hour} * * ? *)" # every day
  schedule_expression_timezone = var.timezone

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.jobs.arn
    role_arn = aws_iam_role.scheduler.arn
    input    = jsonencode({ job = "evening_reminder" })
  }
}

resource "aws_scheduler_schedule" "weekly_summary" {
  name                         = "${var.project_name}-weekly-summary"
  schedule_expression          = "cron(0 19 ? * SUN *)" # Sundays at 7pm
  schedule_expression_timezone = var.timezone

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.jobs.arn
    role_arn = aws_iam_role.scheduler.arn
    input    = jsonencode({ job = "weekly_summary" })
  }
}
