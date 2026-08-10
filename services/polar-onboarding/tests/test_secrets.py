import json
import unittest
from unittest.mock import patch

import boto3
from moto import mock_aws
from src.secrets import get_secret_dict, set_secret_keys

SECRET_NAME = "test/secret"


class TestSecrets(unittest.TestCase):
    def setUp(self):
        self.mock_aws = mock_aws()
        self.mock_aws.start()
        self.client = boto3.client("secretsmanager", region_name="us-east-1")

    def tearDown(self):
        self.mock_aws.stop()

    def test_get_secret_dict_returns_empty_for_missing_secret(self):
        self.assertEqual(get_secret_dict("does-not-exist", "us-east-1"), {})

    def test_set_secret_keys_creates_secret_if_missing(self):
        set_secret_keys(SECRET_NAME, "us-east-1", {"FOO": "bar"})
        self.assertEqual(get_secret_dict(SECRET_NAME, "us-east-1"), {"FOO": "bar"})

    def test_set_secret_keys_merges_without_clobbering_existing_keys(self):
        self.client.create_secret(Name=SECRET_NAME, SecretString=json.dumps({"EXISTING": "value"}))

        set_secret_keys(SECRET_NAME, "us-east-1", {"POLAR_WEBHOOK": "new-secret-key"})

        result = get_secret_dict(SECRET_NAME, "us-east-1")
        self.assertEqual(result["EXISTING"], "value")
        self.assertEqual(result["POLAR_WEBHOOK"], "new-secret-key")

    def test_get_secret_dict_defaults_to_no_explicit_profile(self):
        # profile_name=None is boto3's own default - explicitly asserting
        # it here documents that omitting --aws-profile/AWS_PROFILE falls
        # back to boto3's normal credential resolution, not a hardcoded one.
        with patch("src.secrets.boto3.session.Session") as mock_session:
            mock_session.return_value.client.return_value = self.client
            get_secret_dict(SECRET_NAME, "us-east-1")

        mock_session.assert_called_once_with(profile_name=None)

    def test_set_secret_keys_passes_profile_name_through_to_session(self):
        # boto3.session.Session(profile_name=...) requires that named
        # profile to actually exist locally, which a test environment
        # doesn't have - mock_aws mocks the AWS API calls, not session/
        # profile resolution, so this asserts the constructor call instead
        # of exercising a real named profile end-to-end. set_secret_keys
        # constructs a Session twice (once via its own internal
        # get_secret_dict() read, once for the write) - both must carry the
        # same profile_name through, not just the last one.
        with patch("src.secrets.boto3.session.Session") as mock_session:
            mock_session.return_value.client.return_value = self.client
            set_secret_keys(
                SECRET_NAME, "us-east-1", {"POLAR_WEBHOOK": "shh"}, profile_name="polar-app-prod"
            )

        self.assertGreaterEqual(mock_session.call_count, 1)
        for call in mock_session.call_args_list:
            self.assertEqual(call.kwargs, {"profile_name": "polar-app-prod"})


if __name__ == "__main__":
    unittest.main()
