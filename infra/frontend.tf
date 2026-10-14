# The web app: files in a private S3 bucket, served over HTTPS by CloudFront.

resource "aws_s3_bucket" "frontend" {
  bucket_prefix = "${var.project_name}-web-"
  force_destroy = true # lets `terraform destroy` delete it even with files inside
}

# Nobody can read the bucket directly; only CloudFront can (policy below).
resource "aws_s3_bucket_public_access_block" "frontend" {
  bucket                  = aws_s3_bucket.frontend.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_cloudfront_origin_access_control" "frontend" {
  name                              = "${var.project_name}-web"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# No caching, so a new deploy shows up immediately. With a handful of users,
# serving every request from S3 costs nothing noticeable.
data "aws_cloudfront_cache_policy" "disabled" {
  name = "Managed-CachingDisabled"
}

resource "aws_cloudfront_distribution" "frontend" {
  enabled             = true
  default_root_object = "index.html"
  price_class         = "PriceClass_100" # North America and Europe edges only, the cheapest

  origin {
    origin_id                = "s3-frontend"
    domain_name              = aws_s3_bucket.frontend.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.frontend.id
  }

  default_cache_behavior {
    target_origin_id       = "s3-frontend"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    cache_policy_id        = data.aws_cloudfront_cache_policy.disabled.id
    compress               = true
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

resource "aws_s3_bucket_policy" "frontend" {
  bucket = aws_s3_bucket.frontend.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowCloudFrontToRead"
      Effect    = "Allow"
      Principal = { Service = "cloudfront.amazonaws.com" }
      Action    = "s3:GetObject"
      Resource  = "${aws_s3_bucket.frontend.arn}/*"
      Condition = {
        StringEquals = { "AWS:SourceArn" = aws_cloudfront_distribution.frontend.arn }
      }
    }]
  })

  depends_on = [aws_s3_bucket_public_access_block.frontend]
}

# Upload every file in frontend/. etag makes Terraform re-upload changed files.
locals {
  frontend_dir = "${path.module}/../frontend"
  content_types = {
    html        = "text/html; charset=utf-8"
    css         = "text/css; charset=utf-8"
    js          = "application/javascript; charset=utf-8"
    webmanifest = "application/manifest+json"
  }
}

resource "aws_s3_object" "frontend_files" {
  for_each     = fileset(local.frontend_dir, "*.{html,css,js,webmanifest}")
  bucket       = aws_s3_bucket.frontend.id
  key          = each.value
  source       = "${local.frontend_dir}/${each.value}"
  etag         = filemd5("${local.frontend_dir}/${each.value}")
  content_type = local.content_types[reverse(split(".", each.value))[0]]
}

# config.js is generated here, so the app always points at the right API
# and login page. It isn't in Git because it differs per deployment.
locals {
  frontend_config = {
    apiUrl        = aws_apigatewayv2_api.http.api_endpoint
    cognitoDomain = "https://${aws_cognito_user_pool_domain.main.domain}.auth.${var.aws_region}.amazoncognito.com"
    clientId      = aws_cognito_user_pool_client.web.id
    redirectUri   = "${local.app_url}/"
  }
}

resource "aws_s3_object" "frontend_config" {
  bucket       = aws_s3_bucket.frontend.id
  key          = "config.js"
  content_type = local.content_types["js"]
  content      = "window.APP_CONFIG = ${jsonencode(local.frontend_config)};"
}
