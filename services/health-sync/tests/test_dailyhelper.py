import os
import unittest
from unittest.mock import patch

import boto3
import numpy as np
from moto import mock_aws
from src.app.ETL.dynamo import Health_Record
from src.app.ETL.extractor import HealthData
from src.app.helpers.daily_helper import Daily_Helper
from src.data.loader import load_json

TABLE_NAME = "health_metrics_test"
BUCKET_NAME = "health-metrics-test-bucket"


def _create_table():
    boto3.client("dynamodb", region_name="us-east-1").create_table(
        TableName=TABLE_NAME,
        KeySchema=[
            {"AttributeName": "uid", "KeyType": "HASH"},
            {"AttributeName": "date", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "uid", "AttributeType": "S"},
            {"AttributeName": "date", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )


class TestDailyHelper(unittest.TestCase):
    def setUp(self):
        self.sample_data = load_json("health_extraction.json")
        self.no_data = load_json("no_data.json")
        self.health_data = HealthData(**self.sample_data)
        self.no_health_Data = HealthData(**self.no_data)

        self.config_patcher = patch("src.app.helpers.daily_helper.config_loader")
        mock_config_loader = self.config_patcher.start()
        mock_config_loader.return_value = {"user_id": "user"}

        self.mock_aws = mock_aws()
        self.mock_aws.start()

    def tearDown(self):
        self.mock_aws.stop()
        self.config_patcher.stop()

    def test_no_data_daily_helper(self):
        _create_table()
        os.environ["TABLE_NAME"] = TABLE_NAME
        try:
            load = Daily_Helper(self.no_health_Data)
            processed_data = load.create_load()
            health_record = Health_Record()
            health_record.exists(TABLE_NAME)
            health_record.add_record(processed_data)

            persisted = health_record.get_record(
                uid=processed_data["uid"], date=processed_data["date"]
            )
            self.assertEqual(persisted["uid"], processed_data["uid"])
        finally:
            del os.environ["TABLE_NAME"]

    def test_daily_helper(self):
        _create_table()
        os.environ["TABLE_NAME"] = TABLE_NAME
        try:
            load = Daily_Helper(self.health_data)
            processed_data = load.create_load()
            health_record = Health_Record()
            health_record.exists(TABLE_NAME)
            health_record.add_record(processed_data)

            persisted = health_record.get_record(
                uid=processed_data["uid"], date=processed_data["date"]
            )
            self.assertEqual(persisted["hrv"], processed_data["hrv"])
        finally:
            del os.environ["TABLE_NAME"]

    # Test: A user did not sync their watch yesterday, so the DB is over a day old
    def test_last_update(self):
        _create_table()
        uid = "00000001"
        seeded_date = "2026/07/30"
        health_record = Health_Record()
        health_record.exists(TABLE_NAME)
        health_record.add_record({"uid": uid, "date": seeded_date})

        number_rows = health_record.get_latest_date(uid=uid)
        self.assertTrue(np.isscalar(number_rows))
        self.assertEqual(number_rows, seeded_date)

    def test_s3_upload(self):
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=BUCKET_NAME)
        os.environ["BUCKET_NAME"] = BUCKET_NAME
        os.environ["FOLDER_PATH"] = "daily"
        try:
            load = Daily_Helper(self.health_data)
            load.upload_file()

            objects = boto3.client("s3", region_name="us-east-1").list_objects_v2(
                Bucket=BUCKET_NAME
            )
            self.assertEqual(len(objects["Contents"]), 1)
            self.assertTrue(objects["Contents"][0]["Key"].startswith("daily/"))
        finally:
            del os.environ["BUCKET_NAME"]
            del os.environ["FOLDER_PATH"]

    @patch("src.app.helpers.daily_helper.Push_Notification")
    @patch("src.app.helpers.daily_helper.Transform")
    @patch("src.app.helpers.daily_helper.Extractor")
    def test_send_notification(self, mock_extractor_cls, mock_transform_cls, mock_push_cls):
        mock_extractor = mock_extractor_cls.return_value
        mock_extractor.extraction_decider.return_value = ("2026/07/30", 1)
        mock_extractor.get_activities_for_date.return_value = {"activities": ["a"]}
        mock_transform_cls.return_value.create_metrics.return_value = {"Total_Steps": 5000}
        mock_push_instance = mock_push_cls.return_value

        Daily_Helper().send_daily_notification()

        mock_push_cls.assert_called_once_with({"Total_Steps": 5000})
        mock_push_instance.send_note.assert_called_once()

    def test_create_load_raises_on_missing_response(self):
        # No HealthData passed in - exercises the real AttributeError path,
        # not a mock, since create_load must now raise (not swallow) so a
        # real SQS-triggered failure can retry/DLQ instead of vanishing.
        with self.assertRaises(AttributeError):
            Daily_Helper(response=None).create_load()

    @patch("src.app.helpers.daily_helper.Extractor")
    def test_send_notification_raises_on_extractor_failure(self, mock_extractor_cls):
        mock_extractor_cls.return_value.extraction_decider.side_effect = Exception(
            "Accesslink API down"
        )

        with self.assertRaises(Exception):
            Daily_Helper().send_daily_notification()

    def test_upload_file_raises_on_missing_bucket_env_var(self):
        # BUCKET_NAME deliberately not set - exercises the real
        # os.environ[...] KeyError path.
        with self.assertRaises(KeyError):
            Daily_Helper(self.health_data).upload_file()


if __name__ == "__main__":
    unittest.main()
