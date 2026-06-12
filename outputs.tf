output "api_gateway_url" {
  value = "https://${aws_api_gateway_rest_api.databricks_proxy.id}.execute-api.${var.aws_region}.amazonaws.com/dev"
}

output "lambda_function_name" {
  value = aws_lambda_function.databricks_proxy.function_name
}

