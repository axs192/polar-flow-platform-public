import hashlib
import hmac
import json
import os
import unittest

import boto3
from moto import mock_aws

SECRET_NAME = "test/secret"
META_SECRET = "shh-its-a-meta-secret"
QUEUE_NAME = "PolarUserResponseAI.fifo"


def _sign(body: str) -> str:
    return "sha256=" + hmac.new(META_SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()


def _whatsapp_payload(message_text):
    return {"entry": [{"changes": [{"value": {"messages": [{"text": {"body": message_text}}]}}]}]}


def _event(body_dict, signature=None):
    body = json.dumps(body_dict)
    return {
        "headers": {"X-Hub-Signature-256": signature if signature is not None else _sign(body)},
        "body": body,
        "requestContext": {"requestId": "req-456"},
    }


class TestLambdaHandler(unittest.TestCase):
    def setUp(self):
        os.environ["AWS_APP_SECRET_NAME"] = SECRET_NAME
        os.environ["AWS_APP_REGION"] = "us-east-1"
        os.environ["AWS_DEFAULT_REGION"] = "us-east-1"

        self.mock_aws = mock_aws()
        self.mock_aws.start()

        secrets = boto3.client("secretsmanager", region_name="us-east-1")
        secrets.create_secret(
            Name=SECRET_NAME, SecretString=json.dumps({"META_NOT_SEC": META_SECRET})
        )

        sqs = boto3.client("sqs", region_name="us-east-1")
        queue = sqs.create_queue(QueueName=QUEUE_NAME, Attributes={"FifoQueue": "true"})
        self.queue_url = queue["QueueUrl"]
        os.environ["SQS_USER_QUERY_QUEUE_URL"] = self.queue_url

        import src.app.config_loader as config_loader_module

        config_loader_module.__cached__config = None

    def tearDown(self):
        self.mock_aws.stop()

    def test_missing_signature_returns_400(self):
        from src.app.lambda_handler import lambda_handler

        event = _event(_whatsapp_payload("How was my run?"))
        del event["headers"]["X-Hub-Signature-256"]

        response = lambda_handler(event, None)
        self.assertEqual(response["statusCode"], 400)

    def test_invalid_signature_is_rejected(self):
        from src.app.lambda_handler import lambda_handler

        event = _event(_whatsapp_payload("How was my run?"), signature="sha256=not-real")

        with self.assertRaisesRegex(Exception, "Unauthorized"):
            lambda_handler(event, None)

    def test_valid_message_forwards_text_to_sqs(self):
        from src.app.lambda_handler import lambda_handler

        event = _event(_whatsapp_payload("How was my run?"))
        response = lambda_handler(event, None)

        self.assertEqual(response["statusCode"], 200)

        sqs = boto3.client("sqs", region_name="us-east-1")
        messages = sqs.receive_message(QueueUrl=self.queue_url, MaxNumberOfMessages=1)
        received = messages.get("Messages", [])
        self.assertEqual(len(received), 1)
        self.assertEqual(json.loads(received[0]["Body"]), "How was my run?")

    def test_payload_with_no_message_text_does_not_forward(self):
        from src.app.lambda_handler import lambda_handler

        event = _event({"entry": [{"changes": [{"value": {}}]}]})
        response = lambda_handler(event, None)

        self.assertEqual(response["statusCode"], 200)

        sqs = boto3.client("sqs", region_name="us-east-1")
        messages = sqs.receive_message(QueueUrl=self.queue_url, MaxNumberOfMessages=1)
        self.assertNotIn("Messages", messages)


if __name__ == "__main__":
    unittest.main()
