# Use this code snippet in your app.
# If you need more information about configurations
# or implementing the sample code, visit the AWS docs:
# https://aws.amazon.com/developer/language/python/

import json
import os

import boto3
from botocore.exceptions import ClientError

__cached__config = None


def config_loader():

    global __cached__config
    if __cached__config is not None:
        return __cached__config

    secret_name = os.environ["AWS_APP_SECRET_NAME"]
    region_name = os.environ["AWS_APP_REGION"]

    # Create a Secrets Manager client
    session = boto3.session.Session()
    client = session.client(service_name="secretsmanager", region_name=region_name)

    try:
        response = client.get_secret_value(SecretId=secret_name)
    except ClientError as e:
        # For a list of exceptions thrown, see
        # https://docs.aws.amazon.com/secretsmanager/latest/apireference/API_GetSecretValue.html
        raise e

    __cached__config = json.loads(response["SecretString"])

    return __cached__config
