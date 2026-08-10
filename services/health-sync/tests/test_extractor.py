import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from src.app.ETL.extractor import Extractor


class TestExtractor(unittest.TestCase):
    def setUp(self):
        # Patch config_loader and AccessLink to avoid side effects
        self.extractor = Extractor.__new__(Extractor)
        self.extractor.config = {
            "access_token": "token",
            "client_id": "id",
            "client_secret": "secret",
            "user_id": "user",
        }

    @patch("src.app.ETL.extractor.config_loader")
    @patch("src.app.ETL.extractor.AccessLink")
    def test_extract_pass(self, mock_accesslink, mock_config_loader):
        # Mock config_loader returns valid config
        mock_config_loader.return_value = self.extractor.config

        # Mock AccessLink instance and its activity method
        mock_accesslink_instance = MagicMock()
        mock_accesslink_instance.activity.get_activities_between_date.return_value = {
            "activities": ["a", "b"]
        }
        mock_accesslink.return_value = mock_accesslink_instance

        extractor = Extractor()
        result = extractor.get_activities_for_date()
        self.assertEqual(result, {"activities": ["a", "b"]})

    @patch("src.app.ETL.extractor.config_loader")
    @patch("src.app.ETL.extractor.AccessLink")
    def test_heart_rate_pass(self, mock_accesslink, mock_config_loader):
        # Mock config_loader returns valid config
        mock_config_loader.return_value = self.extractor.config
        # Mock AccessLink instance and its activity method
        mock_accesslink_instance = MagicMock()
        mock_accesslink_instance.heart_rate.get_heartrate_between_date.return_value = {
            "heart_rate": ["a", "b"]
        }
        mock_accesslink.return_value = mock_accesslink_instance

        extractor = Extractor()
        result = extractor.get_heartrate_for_date()
        self.assertEqual(result, {"heart_rate": ["a", "b"]})

    @patch("src.app.ETL.extractor.config_loader")
    @patch("src.app.ETL.extractor.AccessLink")
    def test_sleep_extr_pass(self, mock_accesslink, mock_config_loader):
        mock_config_loader.return_value = self.extractor.config
        # Mock AccessLink instance and its activity method
        mock_accesslink_instance = MagicMock()
        mock_accesslink_instance.sleep.get_sleep_for_date.return_value = {"sleep": ["a", "b"]}
        mock_accesslink.return_value = mock_accesslink_instance

        extractor = Extractor()
        result = extractor.get_sleep_for_date()
        self.assertEqual(result, {"sleep": ["a", "b"]})

    @patch("src.app.ETL.extractor.config_loader")
    @patch("src.app.ETL.extractor.AccessLink")
    def test_recharge_extr_pass(self, mock_accesslink, mock_config_loader):
        mock_config_loader.return_value = self.extractor.config
        # Mock AccessLink instance and its activity method
        mock_accesslink_instance = MagicMock()
        mock_accesslink_instance.recharge.get_recharge_for_date.return_value = {
            "recharge": ["a", "b"]
        }
        mock_accesslink.return_value = mock_accesslink_instance

        extractor = Extractor()
        result = extractor.get_recharge_for_date()
        self.assertEqual(result, {"recharge": ["a", "b"]})

    @patch("src.app.ETL.extractor.config_loader")
    @patch("src.app.ETL.extractor.AccessLink")
    def test_extract_fails(self, mock_accesslink, mock_config_loader):
        mock_config_loader.return_value = self.extractor.config
        mock_accesslink_instance = MagicMock()
        mock_accesslink_instance.activity.get_activities_between_date.side_effect = Exception(
            "API error"
        )
        mock_accesslink.return_value = mock_accesslink_instance

        extractor = Extractor()
        result = extractor.get_activities_for_date()
        self.assertEqual(result, {})

    @patch("src.app.ETL.extractor.config_loader")
    def test_no_access_token(self, mock_config_loader):
        mock_config_loader.return_value = {
            "client_id": "id",
            "client_secret": "secret",
            "user_id": "user",
        }
        with self.assertLogs(level="ERROR") as log:
            Extractor()
        self.assertIn("Authorization is required", "".join(log.output))

    @patch("src.app.ETL.extractor.config_loader")
    def test_failed_to_load_config(self, mock_config_loader):
        mock_config_loader.side_effect = Exception("Config error")
        with self.assertRaises(Exception) as context:
            Extractor()
        self.assertIn("Config error", str(context.exception))

    def test_get_dates_iso_format(self):
        # Provide a specific to_date and days
        to_date = datetime(2025, 9, 26)
        days = 3
        dates = self.extractor._Extractor__get_dates(to_date=to_date, days=days)
        iso_regex = r"\d{4}-\d{2}-\d{2}"
        self.assertRegex(dates["from_date"], iso_regex)
        self.assertRegex(dates["to_date"], iso_regex)

    def test_get_dates_default(self):
        # No arguments, should still return ISO format
        dates = self.extractor._Extractor__get_dates()
        iso_regex = r"\d{4}-\d{2}-\d{2}"
        self.assertRegex(dates["from_date"], iso_regex)
        self.assertRegex(dates["to_date"], iso_regex)

    @patch("src.app.ETL.extractor.AccessLink")
    @patch("src.app.ETL.extractor.config_loader")
    def test_get_physical_info(self, mock_config_loader, mock_accesslink):
        # Mock config
        mock_config_loader.return_value = self.extractor.config

        # Mock transaction object
        mock_transaction = MagicMock()
        mock_transaction.list_physical_infos.return_value = {
            "physical-informations": [
                "https://www.polaraccesslink.com/v3/users/12/physical-information-transactions/12/physical-informations/56",
                "https://www.polaraccesslink.com/v3/users/12/physical-information-transactions/12/physical-informations/120",
            ]
        }
        mock_transaction.get_physical_info.return_value = {
            "id": 123,
            "transaction-id": 179879,
            "created": "2016-04-27T20:11:33.000Z",
        }
        mock_transaction.commit.return_value = None

        # Mock AccessLink.physical_info.create_transaction to return our mock_transaction
        mock_accesslink_instance = MagicMock()
        mock_accesslink_instance.physical_info.create_transaction.return_value = mock_transaction
        mock_accesslink.return_value = mock_accesslink_instance

        extractor = Extractor()
        result = extractor.get_physical_info()

        self.assertEqual(
            result, {"id": 123, "transaction-id": 179879, "created": "2016-04-27T20:11:33.000Z"}
        )
        mock_transaction.commit.assert_called_once()
        # Ensure create_transaction did not raise
        mock_accesslink_instance.physical_info.create_transaction.assert_called_once()


"""
    This returns wrong with this test, because the test is not a true test. It throughs an error if the last updated date in DynamoDB
    is not yesterday.
    def test_extractor_function(self):
        now = datetime.now()
        yesterday = (now - timedelta(days=1))
        today = datetime.now()
        last_update=today
        extract:HealthData = Extractor().extractor(date_1=today, date_2=yesterday, date_3=last_update)
        self.assertEqual(extract.sleep["date"], today.strftime("%Y-%m-%d"))
        self.assertEqual(extract.recharge["date"], today.strftime("%Y-%m-%d"))
        self.assertEqual(extract.heart_rate["heart_rates"][0]["date"], yesterday.strftime("%Y-%m-%d"))
        #self.assertEqual(extract.sleep["date"], today.strftime("%Y-%m-%d")) Daily Activity
"""

if __name__ == "__main__":
    unittest.main()
