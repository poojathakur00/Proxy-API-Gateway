# SETUP.md

How to take this code and run it for your own Databricks apps.

## What this is

A shared AWS API Gateway + Lambda proxy. One deployment serves many
Databricks apps — adding a new app does NOT require new Terraform, only
a swagger file + secrets.

## Prerequisites

- AWS account + AWS CLI configured (`aws configure`)
- Terraform installed
- Python 3.11+ (for the onboarding script)
- A GitHub repo (fork/clone of this code) if you want the automated pipeline

## Step 1 — Deploy the shared infrastructure (one-time)

```bash
terraform init
terraform plan
terraform apply
```

This creates, in your AWS account:
- API Gateway (catch-all `ANY /{proxy+}`, API-key required)
- Router Lambda (`lambda_function.py`, shared by all apps)
- A Lambda Layer for the `requests` library, built from
  `requests-layer/requests-layer.zip` (already in the repo — nothing to
  rebuild, works in any AWS account)
- DynamoDB table `<project>-routes` (empty; one row per app, added later)
- A usage plan (API keys get attached here per app)

Note the outputs — you'll need them next:
```
api_gateway_url
routes_table_name   -> becomes ROUTES_TABLE
usage_plan_id       -> becomes USAGE_PLAN_ID
```

## Step 2 — Set up the onboarding pipeline (one-time)

This step lets you onboard apps by just pushing a swagger file.

1. **Create an IAM user for GitHub Actions** scoped to:
   - `apigateway:CreateApiKey`, `apigateway:CreateUsagePlanKey`, `apigateway:GET`
   - `dynamodb:PutItem`, `dynamodb:GetItem` on the routes table
   - `secretsmanager:CreateSecret`, `secretsmanager:PutSecretValue` on `databricks/*`

   This is needed because GitHub Actions runs on GitHub's servers, not your
   machine — it has no access to your local AWS CLI credentials, so it
   needs its own scoped identity.

   ```bash
   aws iam create-user --user-name github-onboarder

   cat > github-onboarder-policy.json <<EOF
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Action": ["apigateway:CreateApiKey", "apigateway:CreateUsagePlanKey", "apigateway:GET"],
         "Resource": "*"
       },
       {
         "Effect": "Allow",
         "Action": ["dynamodb:PutItem", "dynamodb:GetItem"],
         "Resource": "arn:aws:dynamodb:us-east-2:<your-account-id>:table/<project>-routes"
       },
       {
         "Effect": "Allow",
         "Action": ["secretsmanager:CreateSecret", "secretsmanager:PutSecretValue"],
         "Resource": "arn:aws:secretsmanager:us-east-2:<your-account-id>:secret:databricks/*"
       }
     ]
   }
   EOF

   aws iam put-user-policy --user-name github-onboarder \
     --policy-name github-onboarder-policy \
     --policy-document file://github-onboarder-policy.json

   aws iam create-access-key --user-name github-onboarder
   ```

   The last command prints an Access Key ID and Secret Access Key —
   copy both now, you can't view the secret again later.

2. **Add GitHub repo secrets** (Settings → Secrets and variables → Actions):
   - `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` — for that IAM user

3. **Add GitHub repo variables**:
   - `ROUTES_TABLE` = value of `routes_table_name` output
   - `USAGE_PLAN_ID` = value of `usage_plan_id` output

4. The workflow `.github/workflows/onboard.yml` is already wired to run on
   every push to `swagger/**`.

## Step 3 — Onboard a new Databricks app

1. Add a swagger/OpenAPI file to `swagger/<app-name>.yaml`. Only
   `info.title` is read (used to derive the app's slug) — paths aren't
   enforced, the proxy forwards everything.

2. (Optional, recommended) Add this app's credentials as GitHub secrets,
   named using the app's slug uppercased with underscores. E.g. for
   title "Customer Store API" → slug `customer-store-api` → secret_key
   `CUSTOMER_STORE_API`:
   - `DBX_HOST_CUSTOMER_STORE_API`
   - `DBX_CLIENT_ID_CUSTOMER_STORE_API`
   - `DBX_CLIENT_SECRET_CUSTOMER_STORE_API`
   - `DBX_APP_URL_CUSTOMER_STORE_API`

   If you skip this, the app is onboarded but left disabled with an
   empty secret — you fill it in manually later (Secrets Manager
   console) and flip the DynamoDB row's `enabled` to `true`.

3. Push the swagger file (or run the workflow manually). The pipeline:
   - creates an API key for the app, attaches it to the usage plan
   - writes/updates the app's secret in Secrets Manager (if creds were given)
   - writes a DynamoDB row mapping the API key to the secret, `enabled=true/false`

4. Find the app's API key in the workflow run logs. Give that key to
   whoever will call the proxy — they send it as the `x-api-key` header.

## Step 4 — Test it

```bash
curl https://<api_gateway_url>/<any/path> -H "x-api-key: <the app's key>"
```

The Lambda looks up the key in DynamoDB, fetches the app's secret, gets
an OAuth token from Databricks, and forwards the request.

## Re-running onboarding (e.g. swagger file changes)

Safe to re-run any time. If you don't provide credentials again, the
existing secret and `enabled` flag are left untouched — credentials only
need to be set once per app, not on every swagger change.

## Known limitations (see to-do.txt)

- Terraform state is local only — don't have multiple people run `apply`
  against the same state file without setting up a remote backend first.
- DynamoDB primary key is the raw API key value, not hashed.
- No rate limiting / throttling configured yet.
- No monitoring/alerting on Lambda errors.
