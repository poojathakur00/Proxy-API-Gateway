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

# ---------------------------------------------------------------------------
# Config store: one row per app (keyed by API key id).
# Onboarding writes rows here. Terraform only creates the table.
# ---------------------------------------------------------------------------
resource "aws_dynamodb_table" "routes" {
  name         = "${var.project}-routes"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "api_key_id"

  attribute {
    name = "api_key_id"
    type = "S"
  }
}

# ---------------------------------------------------------------------------
# Router Lambda (single, shared by all apps)
# ---------------------------------------------------------------------------
resource "aws_iam_role" "lambda_role" {
  name = "${var.project}-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Least-privilege: read config + read secrets only.
resource "aws_iam_role_policy" "lambda_access" {
  name = "${var.project}-lambda-access"
  role = aws_iam_role.lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem"]
        Resource = aws_dynamodb_table.routes.arn
      },
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:${var.secret_prefix}*"
      }
    ]
  })
}

resource "aws_lambda_function" "proxy" {
  filename         = "${path.module}/lambda.zip"
  function_name    = "${var.project}-router"
  role             = aws_iam_role.lambda_role.arn
  handler          = "lambda_function.lambda_handler"
  runtime          = "python3.13"
  timeout          = 30
  source_code_hash = filebase64sha256("${path.module}/lambda.zip")

  layers = [
    "arn:aws:lambda:${var.aws_region}:${data.aws_caller_identity.current.account_id}:layer:requests-layer:2"
  ]

  environment {
    variables = {
      ROUTES_TABLE = aws_dynamodb_table.routes.name
    }
  }
}

# ---------------------------------------------------------------------------
# API Gateway: one catch-all API for every app.
#   ANY /{proxy+}  ->  Router Lambda
# API key required so the proxy can identify which app is calling.
# ---------------------------------------------------------------------------
resource "aws_api_gateway_rest_api" "proxy" {
  name = "${var.project}-api"
}

resource "aws_api_gateway_resource" "proxy" {
  rest_api_id = aws_api_gateway_rest_api.proxy.id
  parent_id   = aws_api_gateway_rest_api.proxy.root_resource_id
  path_part   = "{proxy+}"
}

resource "aws_api_gateway_method" "proxy" {
  rest_api_id      = aws_api_gateway_rest_api.proxy.id
  resource_id      = aws_api_gateway_resource.proxy.id
  http_method      = "ANY"
  authorization    = "NONE"
  api_key_required = true
}

resource "aws_api_gateway_integration" "proxy" {
  rest_api_id             = aws_api_gateway_rest_api.proxy.id
  resource_id             = aws_api_gateway_resource.proxy.id
  http_method             = aws_api_gateway_method.proxy.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.proxy.invoke_arn
}

resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.proxy.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.proxy.execution_arn}/*/*"
}

resource "aws_api_gateway_deployment" "proxy" {
  rest_api_id = aws_api_gateway_rest_api.proxy.id
  depends_on  = [aws_api_gateway_integration.proxy]

  triggers = {
    redeployment = sha1(jsonencode([
      aws_api_gateway_resource.proxy.id,
      aws_api_gateway_method.proxy.id,
      aws_api_gateway_integration.proxy.id,
    ]))
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_api_gateway_stage" "main" {
  deployment_id = aws_api_gateway_deployment.proxy.id
  rest_api_id   = aws_api_gateway_rest_api.proxy.id
  stage_name    = var.stage_name
}

# ---------------------------------------------------------------------------
# Usage plan. Required so API keys are enforced. Per-app API keys get
# attached here at onboarding. Throttling/quotas are a later feature.
# ---------------------------------------------------------------------------
resource "aws_api_gateway_usage_plan" "main" {
  name = "${var.project}-usage-plan"

  api_stages {
    api_id = aws_api_gateway_rest_api.proxy.id
    stage  = aws_api_gateway_stage.main.stage_name
  }
}
