# One DynamoDB table for everything (single-table design, see backend/src/db.py).
resource "aws_dynamodb_table" "main" {
  name         = "${var.project_name}-data"
  billing_mode = "PAY_PER_REQUEST" # pay per request, nothing when idle
  hash_key     = "PK"
  range_key    = "SK"

  attribute {
    name = "PK"
    type = "S"
  }

  attribute {
    name = "SK"
    type = "S"
  }

  # Cached food lookups have an "expires_at" time; DynamoDB deletes them for free.
  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
}
