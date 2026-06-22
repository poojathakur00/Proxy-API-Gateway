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

# Usage plan quota/throttle. Tracked per API key, so this is effectively a
# per-app limit even though all apps share one usage plan.
variable "quota_limit" {
  description = "Max requests per app per quota_period"
  default     = 100
}

variable "quota_period" {
  description = "Quota reset period: DAY, WEEK, or MONTH"
  default     = "DAY"
}

variable "throttle_rate_limit" {
  description = "Steady-state requests/sec allowed per app"
  default     = 5
}

variable "throttle_burst_limit" {
  description = "Max burst requests allowed per app"
  default     = 10
}

