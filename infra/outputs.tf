output "app_url" {
  description = "Open this on your phone and laptop"
  value       = local.app_url
}

output "api_url" {
  value = aws_apigatewayv2_api.http.api_endpoint
}

output "user_pool_id" {
  value = aws_cognito_user_pool.main.id
}

output "table_name" {
  value = aws_dynamodb_table.main.name
}
