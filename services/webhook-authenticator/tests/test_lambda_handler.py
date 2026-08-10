import hashlib
import hmac
import json
import os
import unittest

import boto3
from moto import mock_aws

SECRET_NAME = "test/secret"
WEBHOOK_SECRET = "shh-its-a-secret"
QUEUE_NAME = "PolarWebhook.fifo"
EXERCISE_QUEUE_NAME = "ExerciseMessage.fifo"


def _sign(body: str) -> str:
    return hmac.new(WEBHOOK_SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()


def _event(body_dict, signature=None):
    body = json.dumps(body_dict)
    return {
        "headers": {"Polar-Webhook-Signature": signature if signature is not None else _sign(body)},
        "body": body,
        "requestContext": {"requestId": "req-123"},
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
            Name=SECRET_NAME, SecretString=json.dumps({"POLAR_WEBHOOK": WEBHOOK_SECRET})
        )

        sqs = boto3.client("sqs", region_name="us-east-1")
        webhook_queue = sqs.create_queue(QueueName=QUEUE_NAME, Attributes={"FifoQueue": "true"})
        exercise_queue = sqs.create_queue(
            QueueName=EXERCISE_QUEUE_NAME, Attributes={"FifoQueue": "true"}
        )
        self.webhook_queue_url = webhook_queue["QueueUrl"]
        self.exercise_queue_url = exercise_queue["QueueUrl"]

        # config_loader caches globally - reset between tests
        import src.app.config_loader as config_loader_module

        config_loader_module.__cached__config = None

        os.environ["SQS_QUEUE_URL"] = self.webhook_queue_url
        os.environ["SQS_EXERCISE_QUEUE_URL"] = self.exercise_queue_url

    def tearDown(self):
        self.mock_aws.stop()

    def test_ping_event_returns_200_without_signature(self):
        from src.app.lambda_handler import lambda_handler

        event = {
            "headers": {"Polar-Webhook-Event": "PING"},
            "body": json.dumps({"event": "PING", "timestamp": "2019-01-11T08:25:10.02Z"}),
            "requestContext": {"requestId": "req-ping"},
        }

        response = lambda_handler(event, None)

        self.assertEqual(response["statusCode"], 200)

    def test_ping_event_returns_200_even_when_secret_has_no_polar_webhook_key(self):
        """Reproduces the real bootstrap failure: Polar's create-webhook PING
        arrives signed with a key that can't exist in Secrets Manager yet,
        since it's the same key the create call is about to return."""
        from src.app.lambda_handler import lambda_handler

        secrets = boto3.client("secretsmanager", region_name="us-east-1")
        secrets.put_secret_value(SecretId=SECRET_NAME, SecretString=json.dumps({}))
        import src.app.config_loader as config_loader_module

        config_loader_module.__cached__config = None

        event = {
            "headers": {
                "Polar-Webhook-Event": "PING",
                "Polar-Webhook-Signature": "whatever-polar-signs-this-with",
            },
            "body": json.dumps({"event": "PING", "timestamp": "2019-01-11T08:25:10.02Z"}),
            "requestContext": {"requestId": "req-ping"},
        }

        response = lambda_handler(event, None)

        self.assertEqual(response["statusCode"], 200)

    def test_missing_signature_returns_400(self):
        from src.app.lambda_handler import lambda_handler

        event = _event({"event": "SLEEP", "url": "https://example.com"})
        del event["headers"]["Polar-Webhook-Signature"]

        response = lambda_handler(event, None)
        self.assertEqual(response["statusCode"], 400)

    def test_invalid_signature_is_rejected(self):
        from src.app.lambda_handler import lambda_handler

        event = _event(
            {"event": "SLEEP", "url": "https://example.com"}, signature="not-the-real-signature"
        )

        with self.assertRaisesRegex(Exception, "Unauthorized"):
            lambda_handler(event, None)

    def test_sleep_event_dispatches_to_webhook_queue(self):
        from src.app.lambda_handler import lambda_handler

        event = _event({"event": "SLEEP", "url": "https://example.com/sleep"})
        response = lambda_handler(event, None)

        self.assertEqual(response["statusCode"], 200)

        sqs = boto3.client("sqs", region_name="us-east-1")
        messages = sqs.receive_message(QueueUrl=self.webhook_queue_url, MaxNumberOfMessages=1)
        received = messages.get("Messages", [])
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["Body"], "Process Daily Update")

    def test_exercise_event_dispatches_to_exercise_queue(self):
        from src.app.lambda_handler import lambda_handler

        event = _event({"event": "EXERCISE", "url": "https://example.com/exercise"})
        response = lambda_handler(event, None)

        self.assertEqual(response["statusCode"], 200)

        sqs = boto3.client("sqs", region_name="us-east-1")
        messages = sqs.receive_message(QueueUrl=self.exercise_queue_url, MaxNumberOfMessages=1)
        self.assertEqual(len(messages.get("Messages", [])), 1)

    def test_unhandled_event_type_returns_200_without_dispatch(self):
        from src.app.lambda_handler import lambda_handler

        event = _event({"event": "PHYSICAL_INFORMATION", "url": "https://example.com/other"})
        response = lambda_handler(event, None)

        self.assertEqual(response["statusCode"], 200)

        sqs = boto3.client("sqs", region_name="us-east-1")
        webhook_messages = sqs.receive_message(
            QueueUrl=self.webhook_queue_url, MaxNumberOfMessages=1
        )
        exercise_messages = sqs.receive_message(
            QueueUrl=self.exercise_queue_url, MaxNumberOfMessages=1
        )
        self.assertNotIn("Messages", webhook_messages)
        self.assertNotIn("Messages", exercise_messages)


if __name__ == "__main__":
    unittest.main()
