variable "aws_region" {
  default = "us-east-2"
}

variable "project" {
  description = "Name prefix for all resources"
  default     = "databricks-proxy"
}

variable "stage_name" {
  default = "dev"
}

# Lambda may only read secrets whose name starts with this prefix.
# Onboarding creates per-app secrets like "databricks/appA-credentials".
variable "secret_prefix" {
  description = "Prefix for per-app Secrets Manager secrets"
  default     = "databricks/"
}

