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

    # Polar's webhook create/update sends a synchronous PING verification
    # request that must get a 200 OK or the create/update is rejected -
    # confirmed via CloudWatch (KeyError: 'POLAR_WEBHOOK') and Polar's docs.
    # This can arrive before any real secret exists (the signing key it
    # would be signed with is the one about to be returned by this same
    # create call), so it can't be signature-verified like a real event -
    # accepted unconditionally instead, since it has no payload and this
    # handler takes no action on it regardless.
    if decapitlised_headers.get("polar-webhook-event") == "PING":
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps("PING acknowledged"),
        }

    try:
        config = config_loader()
    except Exception as e:
        logging.error("Failed to load config: %s", e)
        raise

    signature = decapitlised_headers.get("polar-webhook-signature")

    if not signature:
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps("Missing Signature"),
        }

    secret = config["POLAR_WEBHOOK"]
    raw_body = event["body"]
    raw_body_bytes = raw_body.encode("utf-8") if isinstance(raw_body, str) else raw_body

    # Verify the signature BEFORE touching the parsed body - untrusted input
    # shouldn't be parsed until its authenticity is confirmed. The deployed
    # version this was recovered from parsed the JSON first; fixed here.
    if not verify_polar_signature(signature, raw_body_bytes, secret):
        logging.warning("Unauthorized: signature verification failed")
        raise Exception("Unauthorized")

    body_dict = json.loads(raw_body)
    url = body_dict["url"]

    if body_dict["event"] == "SLEEP":
        payload = {
            "job_id": event["requestContext"]["requestId"],
            "raw_body": "Process Daily Update",
        }
        send_message_to_sqs(payload, url)

    if body_dict["event"] == "EXERCISE":
        payload = {
            "raw_body": event["body"],
            "job_id": event["requestContext"]["requestId"],
        }
        send_message_to_exercise_load_sqs(payload)

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps("Authenticated Correctly"),
    }


def verify_polar_signature(provided_hmac_hex: str, raw_body: bytes, client_secret: str) -> bool:
    """Verify the signature provided by the Polar Webhook API."""
    key_bytes = client_secret.encode("utf-8")
    computed_hmac = hmac.new(key_bytes, raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed_hmac, provided_hmac_hex)


def send_message_to_sqs(message, url):
    sqs = boto3.client("sqs")
    queue_url = os.environ["SQS_QUEUE_URL"]
    response = sqs.send_message(
        QueueUrl=queue_url,
        MessageBody=str(message["raw_body"]),
        MessageGroupId=str(message["job_id"]),
        MessageDeduplicationId=str(url),
    )
    logging.info("Message sent to Daily Extract SQS: %s", response["MessageId"])


def send_message_to_exercise_load_sqs(message):
    sqs = boto3.client("sqs")
    queue_url = os.environ["SQS_EXERCISE_QUEUE_URL"]
    response = sqs.send_message(
        QueueUrl=queue_url,
        MessageBody=json.dumps(message["raw_body"]),
        MessageGroupId=str(message["job_id"]),
        MessageDeduplicationId=str(message["job_id"]),
    )
    logging.info("Message sent to Exercise SQS: %s", response["MessageId"])
