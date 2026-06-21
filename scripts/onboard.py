#!/usr/bin/env python3
"""Onboard a Databricks app onto the proxy from its swagger file.

Reads the swagger `info.title`, derives a slug, then idempotently:
  1. creates (or reuses) an API key in API Gateway
  2. attaches it to the usage plan
  3. creates an empty secret shell (if missing) for the app's credentials
  4. writes a DynamoDB row mapping the key -> the secret, enabled=false

The app goes live only after you fill the secret with real credentials and
flip the DynamoDB row's `enabled` to true.

Usage:
  python scripts/onboard.py swagger/customer-store-api.yaml
"""
import json
import os
import re
import sys

import boto3
import yaml

# Names are owned by Terraform and passed in via env (terraform output).
REGION = os.environ.get("AWS_REGION", "us-east-2")
ROUTES_TABLE = os.environ["ROUTES_TABLE"]
USAGE_PLAN_ID = os.environ["USAGE_PLAN_ID"]
SECRET_PREFIX = os.environ.get("SECRET_PREFIX", "databricks/")

apigw = boto3.client("apigateway", region_name=REGION)
ddb = boto3.client("dynamodb", region_name=REGION)
secrets = boto3.client("secretsmanager", region_name=REGION)


def slugify(title):
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def get_or_create_key(name):
    """Reuse an existing key with this name, else create one. Idempotent."""
    for k in apigw.get_api_keys(nameQuery=name, includeValues=True)["items"]:
        if k["name"] == name:
            print(f"  key exists: {k['id']}")
            return k["id"], k["value"]
    k = apigw.create_api_key(name=name, enabled=True)
    print(f"  key created: {k['id']}")
    return k["id"], k["value"]


def attach_key(usage_plan_id, key_id):
    try:
        apigw.create_usage_plan_key(
            usagePlanId=usage_plan_id, keyId=key_id, keyType="API_KEY"
        )
        print("  key attached to usage plan")
    except apigw.exceptions.ConflictException:
        print("  key already attached")


def ensure_secret_shell(secret_name):
    """Create an empty secret to be filled in manually. Idempotent."""
    try:
        secrets.create_secret(
            Name=secret_name,
            SecretString=json.dumps(
                {
                    "DBX_HOST": "",
                    "DBX_CLIENT_ID": "",
                    "DBX_CLIENT_SECRET": "",
                    "DBX_APP_URL": "",
                }
            ),
        )
        print(f"  secret shell created: {secret_name}")
    except secrets.exceptions.ResourceExistsException:
        print(f"  secret exists: {secret_name}")


def put_route(key_value, secret_name):
    ddb.put_item(
        TableName=ROUTES_TABLE,
        Item={
            "api_key_id": {"S": key_value},
            "secret_name": {"S": secret_name},
            "enabled": {"BOOL": False},
        },
    )
    print(f"  route written (enabled=false): {secret_name}")


def main(swagger_path):
    with open(swagger_path) as f:
        spec = yaml.safe_load(f)

    title = spec["info"]["title"]
    slug = slugify(title)
    secret_name = f"{SECRET_PREFIX}{slug}-credentials"
    key_name = slug

    print(f"Onboarding '{title}' (slug: {slug})")
    print(f"  expected secret: {secret_name}")

    key_id, key_value = get_or_create_key(key_name)
    attach_key(USAGE_PLAN_ID, key_id)
    ensure_secret_shell(secret_name)
    put_route(key_value, secret_name)

    print("\nDONE (app is DISABLED). API key for this app:")
    print(f"  {key_value}")
    print("\nNext, to go live:")
    print(f"  1. Fill the secret {secret_name} with real values")
    print(f"     (DBX_HOST, DBX_CLIENT_ID, DBX_CLIENT_SECRET, DBX_APP_URL)")
    print(f"  2. Set the DynamoDB row's enabled=true for api_key_id={key_value}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python scripts/onboard.py <swagger.yaml>")
    main(sys.argv[1])
