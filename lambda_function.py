import boto3
import json
import requests

def get_secret():
    client=boto3.client('secretsmanager', region_name='us-east-2')
    response= client.get_secret_value(SecretId='databricks/flask-app-credentials')
    return json.loads(response['SecretString'])


def get_token(dbx_host, client_id, client_secret):
    token_url= f"{dbx_host}/oidc/v1/token"
    response = requests.post(token_url, data={
        "grant_type": "client_credentials",
        "scope": "all-apis"
    }, auth=(client_id, client_secret))

    return response.json()['access_token']

def lambda_handler(event, context):
    
    secrets= get_secret()

    dbx_host= secrets['DBX_HOST']
    client_id= secrets['DBX_CLIENT_ID']
    client_secret= secrets['DBX_CLIENT_SECRET']
    app_url= secrets['DBX_APP_URL']

    token= get_token(dbx_host, client_id, client_secret)

    method= event.get('httpMethod','GET')
    path=event.get('path', '/api/data')
    body= event.get('body', None)

    headers= {
        "Authorization": f"Bearer {token}"
    }
    url= f"{app_url}{path}"

    response = requests.request(
        method = method,
        url = url, 
        headers=headers, 
        json= json.loads(body) if body else None
    )

    return {
        'statusCode': response.status_code,
        'body': response.text,
        'headers': {
            'Content-Type': 'application/json'
        }
    }
