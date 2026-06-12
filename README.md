# AWS API Gateway Proxy for Databricks Apps

A scalable, secure API Gateway solution that acts as a universal proxy between external clients and Databricks (or any backend). Built with AWS API Gateway, Lambda, and Secrets Manager, and provisioned using Terraform.

---

## Architecture Overview

```
External Client (Postman / Python)
        ↓
AWS API Gateway
        ↓
AWS Lambda (Proxy Function)
        ↓
AWS Secrets Manager (Credentials)
        ↓
Databricks Flask App (Backend)
```

The key idea: external clients call a single API Gateway endpoint. Lambda fetches credentials from Secrets Manager, authenticates with the backend, and forwards the request. The client never needs to know about Databricks credentials or authentication.

---

## Project Structure

```
├── main.tf                 # Main Terraform infrastructure
├── variables.tf            # Input variables
├── outputs.tf              # Output values
├── terraform.tfvars        # Variable values (not committed)
├── lambda_function.py      # Lambda proxy code
└── lambda.zip              # Zipped Lambda deployment package
```

---

## Components

### 1. Databricks Flask App

A simple Flask REST API hosted on Databricks Apps with three endpoints:

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/data` | Fetch all records |
| POST | `/data` | Add a new record |
| PUT | `/data/{index}` | Update a record |

The app is secured using a Databricks Service Principal. Authentication is handled automatically via the `x-forwarded-access-token` header when accessed through the Databricks proxy.

**Sample data:**
```json
[{"id": 1, "name": "Sarah"}]
```

### 2. AWS Secrets Manager

Stores Databricks credentials securely. Created manually (not via Terraform) so credentials are managed independently of infrastructure code.

**Secret name:** `databricks/flask-app-credentials`

**Keys stored:**
- `DBX_HOST` - Databricks workspace URL
- `DBX_CLIENT_ID` - Service Principal Client ID
- `DBX_CLIENT_SECRET` - Service Principal Client Secret
- `DBX_APP_URL` - Databricks App URL

### 3. AWS Lambda (Proxy Function)

The core of the solution. On every request, Lambda:
1. Fetches credentials from Secrets Manager
2. Gets an OAuth token from Databricks
3. Forwards the request to the Databricks Flask App
4. Returns the response to the client

```python
def lambda_handler(event, context):
    secrets = get_secret()
    token = get_token(dbx_host, client_id, client_secret)
    response = requests.request(method, url, headers={"Authorization": f"Bearer {token}"}, json=body)
    return {"statusCode": response.status_code, "body": response.text}
```

### 4. AWS API Gateway

Single entry point for all external requests. Routes:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/data` | Fetch all records |
| POST | `/api/data` | Add a new record |
| PUT | `/api/data/{index}` | Update a record |

### 5. IAM Role

A dedicated IAM role for Lambda with two permissions:
- `AWSLambdaBasicExecutionRole` - CloudWatch logging
- `SecretsManagerReadWrite` - Access to Secrets Manager

---

## Terraform Module

The Lambda function and API Gateway are fully provisioned using Terraform. Only the Secrets Manager is created manually.

**Resources managed by Terraform:**
- IAM Role + Policy Attachments
- Lambda Function
- API Gateway (REST API, Resources, Methods, Integrations, Deployment, Stage)
- Lambda Permission for API Gateway

### Usage

```bash
# Initialize
terraform init

# Preview changes
terraform plan

# Apply
terraform apply

# Destroy
terraform destroy
```

**Outputs after apply:**
```
api_gateway_url      = "https://<id>.execute-api.us-east-2.amazonaws.com/dev"
lambda_function_name = "databricks-proxy-tf"
```

---

## Setup Guide

### Prerequisites

- AWS CLI configured (`aws configure`)
- Terraform installed
- Databricks workspace with a Flask App deployed
- Service Principal configured in Databricks App

### Step 1: Create Secrets Manager (Manual)

In AWS Console, create a secret named `databricks/flask-app-credentials` with these keys:

```json
{
  "DBX_HOST": "https://your-workspace.cloud.databricks.com",
  "DBX_CLIENT_ID": "your-service-principal-client-id",
  "DBX_CLIENT_SECRET": "your-service-principal-client-secret",
  "DBX_APP_URL": "https://your-app.aws.databricksapps.com"
}
```

### Step 2: Create Lambda Layer

```bash
mkdir requests-layer
pip install requests -t requests-layer/python
cd requests-layer
zip -r requests-layer.zip python

aws lambda publish-layer-version \
  --layer-name requests-layer \
  --zip-file fileb://requests-layer.zip \
  --compatible-runtimes python3.13 \
  --region us-east-2
```

### Step 3: Configure Terraform

Create `terraform.tfvars`:
```hcl
aws_region = "us-east-2"
```

Update `main.tf` with your Lambda layer ARN.

### Step 4: Deploy with Terraform

```bash
zip lambda.zip lambda_function.py
terraform init
terraform plan
terraform apply
```

### Step 5: Test

Use the API Gateway URL from Terraform output:

```bash
# GET
curl https://<api-id>.execute-api.us-east-2.amazonaws.com/dev/api/data

# POST
curl -X POST https://<api-id>.execute-api.us-east-2.amazonaws.com/dev/api/data \
  -H "Content-Type: application/json" \
  -d '{"id": 2, "name": "John"}'

# PUT
curl -X PUT https://<api-id>.execute-api.us-east-2.amazonaws.com/dev/api/data/0 \
  -H "Content-Type: application/json" \
  -d '{"id": 99, "name": "Emma"}'
```

---

## Scalability

This solution is designed to be backend-agnostic. To add a new backend (e.g., Snowflake):

1. Add new credentials to Secrets Manager
2. Update Lambda routing logic
3. Add new API Gateway resources
4. Run `terraform apply`

No changes needed to the client.

---

## Authentication Flow

```
Client → API Gateway → Lambda
                          ↓
                   Secrets Manager
                   (get credentials)
                          ↓
                   Databricks OAuth
                   (get token)
                          ↓
                   Databricks App
                   (call with token)
                          ↓
                   Response back to client
```

---

## Tech Stack

- **Backend:** Python, Flask, Databricks Apps
- **Cloud:** AWS (API Gateway, Lambda, Secrets Manager, IAM)
- **IaC:** Terraform
- **Auth:** OAuth 2.0, Databricks Service Principal
- **Testing:** Postman, Python requests

---

