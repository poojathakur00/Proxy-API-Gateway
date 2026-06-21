output "api_gateway_url" {
  value = aws_api_gateway_stage.main.invoke_url
}

output "lambda_function_name" {
  value = aws_lambda_function.proxy.function_name
}

output "routes_table_name" {
  value = aws_dynamodb_table.routes.name
}

output "usage_plan_id" {
  value = aws_api_gateway_usage_plan.main.id
}
