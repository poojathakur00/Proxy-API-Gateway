terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

data "aws_caller_identity" "current" {}


# IAM Role for Lambda
resource "aws_iam_role" "lambda_role" {
  name = "lambda-databricks-proxy-role-tf"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "secrets_manager" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/SecretsManagerReadWrite"
}

# Lambda Function
resource "aws_lambda_function" "databricks_proxy" {
  filename      = "lambda.zip"
  function_name = "databricks-proxy-tf"
  role          = aws_iam_role.lambda_role.arn
  handler       = "lambda_function.lambda_handler"
  runtime       = "python3.13"
  source_code_hash = filebase64sha256("lambda.zip")

  layers = [ 
    "arn:aws:lambda:${var.aws_region}:${data.aws_caller_identity.current.account_id}:layer:requests-layer:2"
  ]
}

# API Gateway
resource "aws_api_gateway_rest_api" "databricks_proxy" {
  name = "databricks-proxy-api-tf"
}

resource "aws_api_gateway_resource" "api" {
  rest_api_id = aws_api_gateway_rest_api.databricks_proxy.id
  parent_id   = aws_api_gateway_rest_api.databricks_proxy.root_resource_id
  path_part   = "api"
}

resource "aws_api_gateway_resource" "data" {
  rest_api_id = aws_api_gateway_rest_api.databricks_proxy.id
  parent_id   = aws_api_gateway_resource.api.id
  path_part   = "data"
}

resource "aws_api_gateway_resource" "data_index" {
  rest_api_id = aws_api_gateway_rest_api.databricks_proxy.id
  parent_id   = aws_api_gateway_resource.data.id
  path_part   = "{index}"
}

# GET Method
resource "aws_api_gateway_method" "get_data" {
  rest_api_id   = aws_api_gateway_rest_api.databricks_proxy.id
  resource_id   = aws_api_gateway_resource.data.id
  http_method   = "GET"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "get_data" {
  rest_api_id             = aws_api_gateway_rest_api.databricks_proxy.id
  resource_id             = aws_api_gateway_resource.data.id
  http_method             = aws_api_gateway_method.get_data.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.databricks_proxy.invoke_arn
}

# POST Method
resource "aws_api_gateway_method" "post_data" {
  rest_api_id   = aws_api_gateway_rest_api.databricks_proxy.id
  resource_id   = aws_api_gateway_resource.data.id
  http_method   = "POST"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "post_data" {
  rest_api_id             = aws_api_gateway_rest_api.databricks_proxy.id
  resource_id             = aws_api_gateway_resource.data.id
  http_method             = aws_api_gateway_method.post_data.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.databricks_proxy.invoke_arn
}

# PUT Method
resource "aws_api_gateway_method" "put_data" {
  rest_api_id   = aws_api_gateway_rest_api.databricks_proxy.id
  resource_id   = aws_api_gateway_resource.data_index.id
  http_method   = "PUT"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "put_data" {
  rest_api_id             = aws_api_gateway_rest_api.databricks_proxy.id
  resource_id             = aws_api_gateway_resource.data_index.id
  http_method             = aws_api_gateway_method.put_data.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.databricks_proxy.invoke_arn
}

# Lambda Permission for API Gateway
resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.databricks_proxy.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.databricks_proxy.execution_arn}/*/*"
}

# API Gateway Deployment
resource "aws_api_gateway_deployment" "databricks_proxy" {
  rest_api_id = aws_api_gateway_rest_api.databricks_proxy.id

  depends_on = [
    aws_api_gateway_integration.get_data,
    aws_api_gateway_integration.post_data,
    aws_api_gateway_integration.put_data
  ]
}

resource "aws_api_gateway_stage" "dev" {
  deployment_id = aws_api_gateway_deployment.databricks_proxy.id
  rest_api_id   = aws_api_gateway_rest_api.databricks_proxy.id
  stage_name    = "dev"
}
