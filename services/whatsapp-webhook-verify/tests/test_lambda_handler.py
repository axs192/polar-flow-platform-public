import json
import os
import unittest

import boto3
from moto import mock_aws

SECRET_NAME = "test/secret"
VERIFY_TOKEN = "correct-token"


class TestLambdaHandler(unittest.TestCase):
    def setUp(self):
        os.environ["AWS_APP_SECRET_NAME"] = SECRET_NAME
        os.environ["AWS_APP_REGION"] = "us-east-1"
        os.environ["AWS_DEFAULT_REGION"] = "us-east-1"

        self.mock_aws = mock_aws()
        self.mock_aws.start()

        secrets = boto3.client("secretsmanager", region_name="us-east-1")
        secrets.create_secret(
            Name=SECRET_NAME, SecretString=json.dumps({"META_VERIFY_TOKEN": VERIFY_TOKEN})
        )

        import src.app.config_loader as config_loader_module

        config_loader_module.__cached__config = None

    def tearDown(self):
        self.mock_aws.stop()

    def test_correct_mode_and_token_returns_challenge(self):
        from src.app.lambda_handler import lambda_handler

        event = {
            "queryStringParameters": {
                "hub.mode": "subscribe",
                "hub.verify_token": VERIFY_TOKEN,
                "hub.challenge": "some-challenge-string",
            }
        }
        response = lambda_handler(event, None)
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(response["body"], "some-challenge-string")

    def test_wrong_token_returns_403(self):
        from src.app.lambda_handler import lambda_handler

        event = {
            "queryStringParameters": {
                "hub.mode": "subscribe",
                "hub.verify_token": "wrong-token",
                "hub.challenge": "some-challenge-string",
            }
        }
        response = lambda_handler(event, None)
        self.assertEqual(response["statusCode"], 403)

    def test_null_query_string_params_does_not_raise(self):
        """queryStringParameters can be explicitly null, not just absent."""
        from src.app.lambda_handler import lambda_handler

        event = {"queryStringParameters": None}
        response = lambda_handler(event, None)
        self.assertEqual(response["statusCode"], 403)

    def test_missing_query_string_params_does_not_raise(self):
        from src.app.lambda_handler import lambda_handler

        event = {}
        response = lambda_handler(event, None)
        self.assertEqual(response["statusCode"], 403)

    def test_secret_without_verify_token_key_returns_403_not_keyerror(self):
        """Real bootstrap scenario: the secret exists but hasn't been
        populated with META_VERIFY_TOKEN yet - must fail cleanly, not crash."""
        import src.app.config_loader as config_loader_module
        from src.app.lambda_handler import lambda_handler

        secrets = boto3.client("secretsmanager", region_name="us-east-1")
        secrets.put_secret_value(SecretId=SECRET_NAME, SecretString=json.dumps({}))
        config_loader_module.__cached__config = None

        event = {
            "queryStringParameters": {
                "hub.mode": "subscribe",
                "hub.verify_token": "anything",
                "hub.challenge": "some-challenge-string",
            }
        }
        response = lambda_handler(event, None)
        self.assertEqual(response["statusCode"], 403)


if __name__ == "__main__":
    unittest.main()
