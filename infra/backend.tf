# Two Lambda functions built from the same code:
#   api  - answers every API request (handler.py)
#   jobs - sends the scheduled emails (jobs.py)

data "archive_file" "lambda_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../backend/src"
  output_path = "${path.module}/build/lambda.zip"
  excludes    = ["__pycache__", "__pycache__/**"]
}

locals {
  lambda_assume_role = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

# =====================================================================
# API function
# =====================================================================
resource "aws_iam_role" "lambda" {
  name               = "${var.project_name}-lambda-role"
  assume_role_policy = local.lambda_assume_role
}

resource "aws_iam_role_policy_attachment" "lambda_logs" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Least privilege: only the DynamoDB actions we use, only on our table.
resource "aws_iam_role_policy" "lambda_dynamodb" {
  name = "dynamodb-access"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem", "dynamodb:Query"]
      Resource = aws_dynamodb_table.main.arn
    }]
  })
}

# Calling a model through a "us." inference profile can run it in any US
# region, so the policy allows the profile plus the models behind it.
resource "aws_iam_role_policy" "lambda_bedrock" {
  name = "bedrock-access"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["bedrock:InvokeModel"]
      Resource = [
        "arn:aws:bedrock:*::foundation-model/*",
        "arn:aws:bedrock:*:${local.account_id}:inference-profile/*",
      ]
    }]
  })
}

# Keep logs 14 days (by default they're kept forever and slowly cost money).
resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${var.project_name}-api"
  retention_in_days = 14
}

resource "aws_lambda_function" "api" {
  function_name    = "${var.project_name}-api"
  role             = aws_iam_role.lambda.arn
  runtime          = "python3.12"
  handler          = "handler.lambda_handler"
  filename         = data.archive_file.lambda_zip.output_path
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256 # redeploy when code changes
  timeout          = 25                                               # AI parsing + food lookups can take a few seconds
  memory_size      = 256

  environment {
    variables = {
      TABLE_NAME       = aws_dynamodb_table.main.name
      USDA_API_KEY     = var.usda_api_key
      BEDROCK_MODEL_ID = var.bedrock_model_id
      CONTACT_EMAIL    = var.alert_email
    }
  }

  depends_on = [aws_cloudwatch_log_group.lambda, aws_iam_role_policy_attachment.lambda_logs]
}

# =====================================================================
# Jobs function (scheduled emails)
# =====================================================================
resource "aws_iam_role" "jobs" {
  name               = "${var.project_name}-jobs-role"
  assume_role_policy = local.lambda_assume_role
}

resource "aws_iam_role_policy_attachment" "jobs_logs" {
  role       = aws_iam_role.jobs.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Read-only data access, list users, and send email from your address only.
resource "aws_iam_role_policy" "jobs_access" {
  name = "jobs-access"
  role = aws_iam_role.jobs.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:Query"]
        Resource = aws_dynamodb_table.main.arn
      },
      {
        Effect   = "Allow"
        Action   = ["cognito-idp:ListUsers"]
        Resource = aws_cognito_user_pool.main.arn
      },
      {
        Effect   = "Allow"
        Action   = ["ses:SendEmail"]
        Resource = aws_ses_email_identity.me.arn
      },
    ]
  })
}

resource "aws_cloudwatch_log_group" "jobs" {
  name              = "/aws/lambda/${var.project_name}-jobs"
  retention_in_days = 14
}

resource "aws_lambda_function" "jobs" {
  function_name    = "${var.project_name}-jobs"
  role             = aws_iam_role.jobs.arn
  runtime          = "python3.12"
  handler          = "jobs.lambda_handler"
  filename         = data.archive_file.lambda_zip.output_path
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
  timeout          = 60
  memory_size      = 256

  environment {
    variables = {
      TABLE_NAME   = aws_dynamodb_table.main.name
      USER_POOL_ID = aws_cognito_user_pool.main.id
      SENDER_EMAIL = var.alert_email
      APP_URL      = local.app_url
    }
  }

  depends_on = [aws_cloudwatch_log_group.jobs, aws_iam_role_policy_attachment.jobs_logs]
}
