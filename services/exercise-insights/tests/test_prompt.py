import os
import unittest

import boto3
from botocore.exceptions import ClientError
from exercise_insights.core.prompts_loader import get_prompt
from moto import mock_aws

BUCKET_NAME = "polar-response-prompts-test"
EXERCISE_PROMPT_KEY = "exercise_prompt.txt"
HEALTH_PROMPT_KEY = "health_prompt.txt"


class TestPromptCreation(unittest.TestCase):
    def setUp(self):
        self.mock_aws = mock_aws()
        self.mock_aws.start()

        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=BUCKET_NAME)
        s3.put_object(
            Bucket=BUCKET_NAME,
            Key=EXERCISE_PROMPT_KEY,
            Body=b"You are an assistant summarizing exercise data.",
        )
        s3.put_object(
            Bucket=BUCKET_NAME,
            Key=HEALTH_PROMPT_KEY,
            Body=b"You are an assistant summarizing health data.",
        )

        os.environ["BUCKET_NAME"] = BUCKET_NAME
        os.environ["EXERCISE_PROMPT_PATH"] = EXERCISE_PROMPT_KEY
        os.environ["HEALTH_PROMPT_PATH"] = HEALTH_PROMPT_KEY

    def tearDown(self):
        self.mock_aws.stop()
        for key in ("BUCKET_NAME", "EXERCISE_PROMPT_PATH", "HEALTH_PROMPT_PATH"):
            del os.environ[key]

    def test_given_exercise_prompt_in_s3_then_content_returned(self):
        result = get_prompt(exercise=True)
        self.assertEqual(result, "You are an assistant summarizing exercise data.")

    def test_given_health_prompt_in_s3_then_content_returned(self):
        result = get_prompt(health=True)
        self.assertEqual(result, "You are an assistant summarizing health data.")

    def test_given_missing_key_then_raises_and_logs(self):
        os.environ["EXERCISE_PROMPT_PATH"] = "does-not-exist.txt"
        with self.assertLogs(level="ERROR"), self.assertRaises(ClientError):
            get_prompt(exercise=True)


if __name__ == "__main__":
    unittest.main()
