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


def mask(value):
    """Tell the GitHub Actions runner to redact this value from all log output."""
    print(f"::add-mask::{value}")


def get_or_create_key(name):
    """Reuse an existing key with this name, else create one. Idempotent."""
    for k in apigw.get_api_keys(nameQuery=name, includeValues=True)["items"]:
        if k["name"] == name:
            mask(k["value"])
            print(f"  key exists: {k['id']}")
            return k["id"], k["value"]
    k = apigw.create_api_key(name=name, enabled=True)
    mask(k["value"])
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


def credentials_from_env():
    """Read DBX_HOST/CLIENT_ID/CLIENT_SECRET/APP_URL from env, if all present."""
    values = {
        "DBX_HOST": os.environ.get("DBX_HOST", ""),
        "DBX_CLIENT_ID": os.environ.get("DBX_CLIENT_ID", ""),
        "DBX_CLIENT_SECRET": os.environ.get("DBX_CLIENT_SECRET", ""),
        "DBX_APP_URL": os.environ.get("DBX_APP_URL", ""),
    }
    return values if all(values.values()) else None


def upsert_secret(secret_name, values):
    """Create or update the secret with real values. Idempotent."""
    body = json.dumps(values)
    try:
        secrets.create_secret(Name=secret_name, SecretString=body)
        print(f"  secret created: {secret_name}")
    except secrets.exceptions.ResourceExistsException:
        secrets.put_secret_value(SecretId=secret_name, SecretString=body)
        print(f"  secret updated: {secret_name}")


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


def get_existing_route(key_value):
    """Return the current route item for this key, or None if not onboarded yet."""
    resp = ddb.get_item(TableName=ROUTES_TABLE, Key={"api_key_id": {"S": key_value}})
    return resp.get("Item")


def put_route(key_value, secret_name, enabled):
    ddb.put_item(
        TableName=ROUTES_TABLE,
        Item={
            "api_key_id": {"S": key_value},
            "secret_name": {"S": secret_name},
            "enabled": {"BOOL": enabled},
        },
    )
    print(f"  route written (enabled={enabled}): {secret_name}")


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

    creds = credentials_from_env()
    existing = get_existing_route(key_value)

    if creds:
        upsert_secret(secret_name, creds)
        put_route(key_value, secret_name, enabled=True)
        print("\nDONE (app is ENABLED, credentials loaded from env).")
    elif existing:
        # Already onboarded; no new creds given this run — leave secret and
        # enabled flag exactly as they are (e.g. set manually earlier).
        print(f"  route already exists, leaving as-is (enabled={existing['enabled']['BOOL']})")
        print("\nDONE (no changes; no credentials provided, app already onboarded).")
    else:
        ensure_secret_shell(secret_name)
        put_route(key_value, secret_name, enabled=False)
        print("\nDONE (app is DISABLED, no credentials provided).")
        print(f"To go live:")
        print(f"  1. Fill the secret {secret_name} with real values")
        print(f"     (DBX_HOST, DBX_CLIENT_ID, DBX_CLIENT_SECRET, DBX_APP_URL)")
        print(f"  2. Set the DynamoDB row's enabled=true for api_key_id={key_value}")

    print(f"\nAPI key for this app: {key_value}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python scripts/onboard.py <swagger.yaml>")
    main(sys.argv[1])
