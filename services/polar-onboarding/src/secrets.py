"""Read-modify-write helper for the shared Secrets Manager secret.

Every other service in this repo reads one shared secret (or, per the
cost-conscious decision in docs/architecture.md, at most two going
forward) holding several unrelated keys. This does a read-modify-write
so setting one key never clobbers the others already in there.
"""

import json

import boto3
from botocore.exceptions import ClientError


def get_secret_dict(secret_name: str, region_name: str, profile_name: str | None = None) -> dict:
    client = boto3.session.Session(profile_name=profile_name).client(
        "secretsmanager", region_name=region_name
    )
    try:
        response = client.get_secret_value(SecretId=secret_name)
        return json.loads(response["SecretString"])
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            return {}
        raise


def set_secret_keys(
    secret_name: str, region_name: str, updates: dict, profile_name: str | None = None
) -> None:
    """Merge `updates` into the existing secret's JSON and write it back.

    Creates the secret if it doesn't exist yet. `profile_name` (an AWS CLI
    profile, e.g. "polar-app-prod") defaults to None, which lets boto3 fall
    back to its usual default-credential resolution - explicit is safer,
    since this repo's convention is that unspecified credentials resolve to
    the *old* AWS account, not the new one this tool is meant to write to.
    """
    client = boto3.session.Session(profile_name=profile_name).client(
        "secretsmanager", region_name=region_name
    )
    current = get_secret_dict(secret_name, region_name, profile_name=profile_name)
    current.update(updates)
    payload = json.dumps(current)

    try:
        client.put_secret_value(SecretId=secret_name, SecretString=payload)
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            client.create_secret(Name=secret_name, SecretString=payload)
        else:
            raise
