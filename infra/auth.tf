# Login with Amazon Cognito.
# The pool is invite-only: Terraform creates ONE user (you), and nobody else
# can sign up. That protects your data and your AI credits.

resource "aws_cognito_user_pool" "main" {
  name                     = "${var.project_name}-users"
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]
  deletion_protection      = "INACTIVE" # so `terraform destroy` can remove it

  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }
}

# Cognito emails this user a temporary password. You choose a new one at first login.
resource "aws_cognito_user" "me" {
  user_pool_id = aws_cognito_user_pool.main.id
  username     = var.alert_email

  attributes = {
    email          = var.alert_email
    email_verified = "true"
  }
}

# Hosts Cognito's ready-made login page at
# https://<prefix>.auth.<region>.amazoncognito.com
resource "aws_cognito_user_pool_domain" "main" {
  domain       = "${var.project_name}-${local.account_id}"
  user_pool_id = aws_cognito_user_pool.main.id
}

# The web app's login settings. No client secret, because a browser app
# can't keep one hidden; it uses PKCE instead (see frontend/auth.js).
resource "aws_cognito_user_pool_client" "web" {
  name         = "${var.project_name}-web"
  user_pool_id = aws_cognito_user_pool.main.id

  generate_secret                      = false
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email"]
  supported_identity_providers         = ["COGNITO"]
  callback_urls                        = ["${local.app_url}/"]
  logout_urls                          = ["${local.app_url}/"]
  explicit_auth_flows                  = ["ALLOW_USER_SRP_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"]
  prevent_user_existence_errors        = "ENABLED"

  # Short-lived access tokens; the app quietly refreshes them for 30 days.
  access_token_validity  = 1
  id_token_validity      = 1
  refresh_token_validity = 30

  token_validity_units {
    access_token  = "hours"
    id_token      = "hours"
    refresh_token = "days"
  }
}
