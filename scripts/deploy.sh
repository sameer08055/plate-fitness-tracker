#!/usr/bin/env bash
# One command to test and deploy everything:  ./scripts/deploy.sh
set -euo pipefail
cd "$(dirname "$0")/.."

export AWS_PROFILE="${AWS_PROFILE:-fitness}"

echo "Running unit tests..."
(cd backend && .venv/bin/python -m pytest -q)

echo "Getting AWS credentials for Terraform..."
if ! creds="$(aws configure export-credentials --format env 2>/dev/null)"; then
  echo "Your AWS login has expired. Run: aws login --profile $AWS_PROFILE"
  exit 1
fi
eval "$creds"

echo "Deploying..."
cd infra
terraform fmt -recursive
terraform apply
echo
echo "App: $(terraform output -raw app_url)"
