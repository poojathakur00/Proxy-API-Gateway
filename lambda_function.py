import json
import os

import boto3
import requests

REGION = os.environ.get("AWS_REGION", "us-east-2")
ROUTES_TABLE = os.environ["ROUTES_TABLE"]

dynamodb = boto3.resource("dynamodb", region_name=REGION)
secrets_client = boto3.client("secretsmanager", region_name=REGION)
routes = dynamodb.Table(ROUTES_TABLE)

# Simple in-memory caches (persist while the container is warm).
_config_cache = {}
_secret_cache = {}


def get_app_config(api_key_id):
    """Look up which backend this caller's API key maps to."""
    if api_key_id in _config_cache:
        return _config_cache[api_key_id]

    resp = routes.get_item(Key={"api_key_id": api_key_id})
    item = resp.get("Item")
    if item:
        _config_cache[api_key_id] = item
    return item


def get_secret(secret_name):
    if secret_name in _secret_cache:
        return _secret_cache[secret_name]

    resp = secrets_client.get_secret_value(SecretId=secret_name)
    secret = json.loads(resp["SecretString"])
    _secret_cache[secret_name] = secret
    return secret


def get_token(dbx_host, client_id, client_secret):
    resp = requests.post(
        f"{dbx_host}/oidc/v1/token",
        data={"grant_type": "client_credentials", "scope": "all-apis"},
        auth=(client_id, client_secret),
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def respond(status, body):
    return {
        "statusCode": status,
        "body": json.dumps(body),
        "headers": {"Content-Type": "application/json"},
    }


def lambda_handler(event, context):
    # API Gateway (AWS_PROXY) passes the validated API key here.
    api_key_id = event.get("requestContext", {}).get("identity", {}).get("apiKey")
    if not api_key_id:
        return respond(401, {"error": "missing API key"})

    config = get_app_config(api_key_id)
    if not config:
        return respond(403, {"error": "unknown API key"})
    if not config.get("enabled", True):
        return respond(403, {"error": "app disabled"})

    secret = get_secret(config["secret_name"])
    token = get_token(
        secret["DBX_HOST"], secret["DBX_CLIENT_ID"], secret["DBX_CLIENT_SECRET"]
    )

    # Forward the original request unchanged to the app's backend.
    method = event.get("httpMethod", "GET")
    path = event.get("path", "/")
    query = event.get("queryStringParameters") or None
    body = event.get("body")

    resp = requests.request(
        method=method,
        url=f"{secret['DBX_APP_URL']}{path}",
        headers={"Authorization": f"Bearer {token}"},
        params=query,
        json=json.loads(body) if body else None,
    )

    return {
        "statusCode": resp.status_code,
        "body": resp.text,
        "headers": {"Content-Type": "application/json"},
    }
