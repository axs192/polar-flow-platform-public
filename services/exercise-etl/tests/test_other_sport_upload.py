import os
import unittest
from unittest.mock import patch

import boto3
from moto import mock_aws
from src.app.ETL.load import loader
from src.app.ETL.load_creator import load_creator
from src.data.loader import load_json

TABLE_NAME = "exercise_data_test"


class TestUploadOtherData(unittest.TestCase):
    def setUp(self):
        self.sample_data = load_json("other_data_sample.json")
        os.environ["TABLE_NAME"] = TABLE_NAME

        self.mock_aws = mock_aws()
        self.mock_aws.start()
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

    def tearDown(self):
        self.mock_aws.stop()
        del os.environ["TABLE_NAME"]

    @patch("src.app.ETL.load_creator.config_loader")
    def test_given_correct_data_then_record_is_persisted(self, mock_config_loader):
        mock_config_loader.return_value = {"user_id": "user"}

        load = load_creator(response=self.sample_data).create_load()
        table_name = os.environ["TABLE_NAME"]
        upload = loader()
        upload.exists(table_name=table_name)
        upload.add_record(load=load)

        persisted = upload.table.get_item(Key={"uid": load["uid"], "date": load["date"]})
        self.assertEqual(persisted["Item"]["uid"], load["uid"])


if __name__ == "__main__":
    unittest.main()
