# The public HTTPS API. Every route requires a valid Cognito login token,
# checked by API Gateway BEFORE Lambda runs (so bad requests cost nothing).

resource "aws_apigatewayv2_api" "http" {
  name          = "${var.project_name}-api"
  protocol_type = "HTTP"

  # Only our own web app may call this API from a browser.
  cors_configuration {
    allow_origins = [local.app_url]
    allow_methods = ["GET", "POST", "PUT", "DELETE"]
    allow_headers = ["authorization", "content-type"]
    max_age       = 3600
  }
}

resource "aws_apigatewayv2_authorizer" "cognito" {
  api_id           = aws_apigatewayv2_api.http.id
  name             = "cognito"
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]

  jwt_configuration {
    audience = [aws_cognito_user_pool_client.web.id]
    issuer   = "https://${aws_cognito_user_pool.main.endpoint}"
  }
}

resource "aws_apigatewayv2_integration" "lambda" {
  api_id                 = aws_apigatewayv2_api.http.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api.invoke_arn
  payload_format_version = "2.0"
}

# Must match the ROUTES dictionary in backend/src/handler.py.
locals {
  routes = [
    "PUT /goals",
    "GET /goals",
    "POST /meals",
    "POST /meals/parse",
    "DELETE /days/{date}/meals/{id}",
    "POST /workouts",
    "DELETE /days/{date}/workouts/{id}",
    "POST /sleep",
    "GET /days/{date}",
    "GET /insights",
    "GET /foods/search",
    "GET /barcode/{code}",
  ]
}

resource "aws_apigatewayv2_route" "routes" {
  for_each           = toset(local.routes)
  api_id             = aws_apigatewayv2_api.http.id
  route_key          = each.value
  target             = "integrations/${aws_apigatewayv2_integration.lambda.id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito.id
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.http.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_burst_limit = 10
    throttling_rate_limit  = 5
  }

  # AI parsing is the only route that costs real money per call, so it gets
  # a much lower limit.
  route_settings {
    route_key              = "POST /meals/parse"
    throttling_burst_limit = 2
    throttling_rate_limit  = 1
  }

  depends_on = [aws_apigatewayv2_route.routes]
}

# Allow API Gateway to invoke the API Lambda function.
resource "aws_lambda_permission" "api" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.http.execution_arn}/*/*"
}
