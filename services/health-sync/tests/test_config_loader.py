import json
import os
import unittest
from unittest.mock import patch

import boto3
from moto import mock_aws
from src.app.helpers import config_loader as config_loader_module
from src.app.helpers.config_loader import config_loader

SECRET_NAME = "prod/smsApp"
REGION = "us-east-1"


class TestConfigLoader(unittest.TestCase):
    def setUp(self):
        # config_loader() caches its result in a module-level global, which
        # would otherwise leak the value (or lack of one) from one test into
        # the next regardless of what each test mocks.
        # setattr, not dotted assignment: "__cached__config" (2 leading
        # underscores, 0 trailing) is exactly the shape Python name-mangles
        # when written literally inside a class body, so
        # `config_loader_module.__cached__config = None` here would silently
        # set an unrelated `_TestConfigLoader__cached__config` attribute
        # instead of resetting the module's real cache.
        setattr(config_loader_module, "__cached__config", None)
        os.environ["AWS_APP_SECRET_NAME"] = SECRET_NAME
        os.environ["AWS_APP_REGION"] = REGION

        self.mock_aws = mock_aws()
        self.mock_aws.start()

    def tearDown(self):
        self.mock_aws.stop()
        setattr(config_loader_module, "__cached__config", None)
        del os.environ["AWS_APP_SECRET_NAME"]
        del os.environ["AWS_APP_REGION"]

    def _create_secret(self, value: dict):
        boto3.client("secretsmanager", region_name=REGION).create_secret(
            Name=SECRET_NAME, SecretString=json.dumps(value)
        )

    def test_returns_parsed_secret_json(self):
        self._create_secret({"client_id": "cid", "access_token": "tok"})

        result = config_loader()

        self.assertEqual(result, {"client_id": "cid", "access_token": "tok"})

    def test_second_call_is_served_from_cache_not_a_second_api_call(self):
        self._create_secret({"client_id": "cid"})
        config_loader()

        with patch(
            "src.app.helpers.config_loader.boto3.session.Session"
        ) as mock_session:
            result = config_loader()

        mock_session.assert_not_called()
        self.assertEqual(result, {"client_id": "cid"})

    def test_missing_secret_reraises_client_error(self):
        # No secret created - get_secret_value raises ResourceNotFoundException,
        # which config_loader() re-raises rather than swallowing.
        from botocore.exceptions import ClientError

        with self.assertRaises(ClientError):
            config_loader()


if __name__ == "__main__":
    unittest.main()
