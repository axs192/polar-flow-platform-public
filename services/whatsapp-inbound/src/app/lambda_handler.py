import hashlib
import hmac
import json
import logging
import os

import boto3

from .config_loader import config_loader


def lambda_handler(event, context):

    headers = event["headers"]
    decapitlised_headers = {k.lower(): v for k, v in headers.items()}
    signature = decapitlised_headers.get("x-hub-signature-256")

    if signature and signature.startswith("sha256="):
        signature = signature[len("sha256=") :]

    if not signature:
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps("Missing Signature"),
        }

    # Loaded per-invocation rather than at module import time (as the
    # deployed version this was recovered from did) - config_loader()
    # caches internally anyway, and this avoids a live Secrets Manager
    # call as a side effect of merely importing this module.
    config = config_loader()
    secret = config["META_NOT_SEC"]

    raw_body = event.get("body") or ""
    raw_body_bytes = raw_body.encode("utf-8") if isinstance(raw_body, str) else raw_body

    if not verify_signature(signature, raw_body_bytes, secret):
        logging.warning("Unauthorized: signature verification failed")
        raise Exception("Unauthorized")

    text_body = extract_message_text(event=event)

    if text_body is not None:
        payload = {
            "raw_body": text_body,
            "job_id": event["requestContext"]["requestId"],
        }
        send_message_sqs(payload)

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps("Authenticated Correctly"),
    }


def verify_signature(provided_hmac_hex: str, raw_body: bytes, client_secret: str) -> bool:
    """Verify the signature provided by the Meta Webhook API."""
    key_bytes = client_secret.encode("utf-8")
    computed_hmac = hmac.new(key_bytes, raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed_hmac, provided_hmac_hex)


def extract_message_text(event):
    """Extract the inbound WhatsApp message text, if present."""
    body = event.get("body")
    if not body:
        return None
    try:
        data = json.loads(body)
    except Exception as e:
        logging.error("Failed to parse body as JSON: %s", e)
        return None

    path = ["entry", 0, "changes", 0, "value", "messages", 0, "text", "body"]
    return get_nested(data, path)


def get_nested(data, path, default=None):
    for key in path:
        try:
            data = data[key] if isinstance(key, int) else data.get(key, default)
        except (IndexError, AttributeError, KeyError, TypeError):
            return default
        if data is None:
            return default
    return data


def send_message_sqs(message):
    sqs = boto3.client("sqs")
    # Was SQS_EXERCISE_QUEUE_URL in the deployed version - a copy-paste
    # leftover from webhook-authenticator that actually held the
    # PolarUserResponseAI.fifo URL, not an exercise queue. Renamed to match
    # what it actually is.
    queue_url = os.environ["SQS_USER_QUERY_QUEUE_URL"]
    response = sqs.send_message(
        QueueUrl=queue_url,
        MessageBody=json.dumps(message["raw_body"]),
        MessageGroupId=str(message["job_id"]),
        MessageDeduplicationId=str(message["job_id"]),
    )
    logging.info("Message sent to user-query SQS: %s", response["MessageId"])
