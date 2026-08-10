import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import boto3
import responses
from freezegun import freeze_time
from moto import mock_aws
from src.app.ETL.extractor import Extractor, HealthData

BASE_URL = "https://www.polaraccesslink.com/v3"
FULL_CONFIG = {
    "client_id": "cid",
    "client_secret": "csecret",
    "access_token": "token-123",
    "user_id": "user-1",
}


def _extractor(config=FULL_CONFIG):
    with patch("src.app.ETL.extractor.config_loader", return_value=config):
        return Extractor()


class TestExtractorInit(unittest.TestCase):
    def test_config_loader_failure_reraises(self):
        with patch(
            "src.app.ETL.extractor.config_loader",
            side_effect=RuntimeError("Secrets Manager down"),
        ), self.assertRaises(RuntimeError):
            Extractor()

    def test_missing_access_token_skips_accesslink_setup(self):
        extractor = _extractor(config={"client_id": "cid", "client_secret": "csecret"})

        self.assertFalse(hasattr(extractor, "accesslink"))

    def test_accesslink_init_failure_reraises(self):
        with (
            patch("src.app.ETL.extractor.config_loader", return_value=FULL_CONFIG),
            patch("src.app.ETL.extractor.AccessLink", side_effect=ValueError("bad creds")),
            self.assertRaises(ValueError),
        ):
            Extractor()


class TestGetDatesViaActivities(unittest.TestCase):
    """__get_dates is private; exercised indirectly through the real request
    URL a public method builds from it, under a frozen "now"."""

    @responses.activate
    @freeze_time("2026-08-05")
    def test_no_kwargs_defaults_to_yesterday_minus_4_days(self):
        # to_date = now - 1 day = 2026-08-04; from_date = to_date - 4 days = 2026-07-31
        responses.add(
            responses.GET,
            f"{BASE_URL}/users/activities/?from=2026-07-31&to=2026-08-04",
            json={"activities": []},
            status=200,
        )

        result = _extractor().get_activities_for_date()

        self.assertEqual(result, {"activities": []})

    @responses.activate
    @freeze_time("2026-08-05")
    def test_to_date_kwarg_without_days_defaults_to_4_day_window(self):
        responses.add(
            responses.GET,
            f"{BASE_URL}/users/activities/?from=2026-08-01&to=2026-08-05",
            json={"activities": []},
            status=200,
        )

        result = _extractor().get_activities_for_date(to_date=datetime(2026, 8, 5))

        self.assertEqual(result, {"activities": []})

    @responses.activate
    @freeze_time("2026-08-05")
    def test_to_date_and_days_kwargs_both_respected(self):
        responses.add(
            responses.GET,
            f"{BASE_URL}/users/activities/?from=2026-07-29&to=2026-08-05",
            json={"activities": []},
            status=200,
        )

        result = _extractor().get_activities_for_date(to_date=datetime(2026, 8, 5), days=7)

        self.assertEqual(result, {"activities": []})


class TestAccessLinkCallsSucceedAndFailGracefully(unittest.TestCase):
    """Each of these swallows AccessLink errors into an empty result rather
    than raising - real, existing behavior worth locking in."""

    @responses.activate
    def test_get_activities_for_date_401_returns_empty_dict(self):
        responses.add(
            responses.GET,
            f"{BASE_URL}/users/activities/?from=2026-01-01&to=2026-01-01",
            json={"error": "unauthorized"},
            status=401,
        )

        result = _extractor().get_activities_for_date(to_date=datetime(2026, 1, 1), days=0)

        self.assertEqual(result, {})

    @responses.activate
    def test_get_heartrate_for_date_success(self):
        responses.add(
            responses.GET,
            f"{BASE_URL}/users/continuous-heart-rate?from=2026-01-01&to=2026-01-01",
            json={"samples": []},
            status=200,
        )

        result = _extractor().get_heartrate_for_date(to_date=datetime(2026, 1, 1), days=0)

        self.assertEqual(result, {"samples": []})

    @responses.activate
    def test_get_heartrate_for_date_500_returns_empty_dict(self):
        responses.add(
            responses.GET,
            f"{BASE_URL}/users/continuous-heart-rate?from=2026-01-01&to=2026-01-01",
            json={"error": "server_error"},
            status=500,
        )

        result = _extractor().get_heartrate_for_date(to_date=datetime(2026, 1, 1), days=0)

        self.assertEqual(result, {})

    @responses.activate
    def test_get_sleep_for_date_success(self):
        responses.add(
            responses.GET, f"{BASE_URL}/users/sleep/2026-01-01", json={"sleep": "data"}, status=200
        )

        result = _extractor().get_sleep_for_date(to_date=datetime(2026, 1, 1))

        self.assertEqual(result, {"sleep": "data"})

    @responses.activate
    def test_get_sleep_for_date_404_returns_empty_dict(self):
        responses.add(
            responses.GET, f"{BASE_URL}/users/sleep/2026-01-01", json={"error": "none"}, status=404
        )

        result = _extractor().get_sleep_for_date(to_date=datetime(2026, 1, 1))

        self.assertEqual(result, {})

    @responses.activate
    @freeze_time("2026-08-05")
    def test_get_todays_sleep_uses_todays_date_and_returns_result(self):
        responses.add(
            responses.GET, f"{BASE_URL}/users/sleep/2026-08-05", json={"sleep": "today"}, status=200
        )

        result = _extractor().get_todays_sleep()

        self.assertEqual(result, {"sleep": "today"})

    @responses.activate
    @freeze_time("2026-08-05")
    def test_get_todays_sleep_failure_returns_empty_dict(self):
        responses.add(
            responses.GET, f"{BASE_URL}/users/sleep/2026-08-05", json={"error": "x"}, status=500
        )

        result = _extractor().get_todays_sleep()

        self.assertEqual(result, {})

    @responses.activate
    def test_get_recharge_for_date_success(self):
        responses.add(
            responses.GET,
            f"{BASE_URL}/users/nightly-recharge/2026-01-01",
            json={"recharge": 80},
            status=200,
        )

        result = _extractor().get_recharge_for_date(to_date=datetime(2026, 1, 1))

        self.assertEqual(result, {"recharge": 80})

    @responses.activate
    def test_get_recharge_for_date_failure_returns_empty_dict(self):
        responses.add(
            responses.GET,
            f"{BASE_URL}/users/nightly-recharge/2026-01-01",
            json={"error": "x"},
            status=500,
        )

        result = _extractor().get_recharge_for_date(to_date=datetime(2026, 1, 1))

        self.assertEqual(result, {})

    @responses.activate
    @freeze_time("2026-08-05")
    def test_get_todays_recharge_success(self):
        responses.add(
            responses.GET,
            f"{BASE_URL}/users/nightly-recharge/2026-08-05",
            json={"recharge": 90},
            status=200,
        )

        result = _extractor().get_todays_recharge()

        self.assertEqual(result, {"recharge": 90})

    @responses.activate
    @freeze_time("2026-08-05")
    def test_get_todays_recharge_failure_returns_empty_dict(self):
        responses.add(
            responses.GET,
            f"{BASE_URL}/users/nightly-recharge/2026-08-05",
            json={"error": "x"},
            status=500,
        )

        result = _extractor().get_todays_recharge()

        self.assertEqual(result, {})

    @responses.activate
    def test_get_exercises_success(self):
        responses.add(
            responses.GET,
            f"{BASE_URL}/exercises?samples=True&zones=False&route=False",
            json=[{"id": "ex-1"}],
            status=200,
        )

        result = _extractor().get_exercises()

        self.assertEqual(result, [{"id": "ex-1"}])

    @responses.activate
    def test_get_exercises_failure_returns_empty_list(self):
        responses.add(
            responses.GET,
            f"{BASE_URL}/exercises?samples=True&zones=False&route=False",
            json={"error": "x"},
            status=500,
        )

        result = _extractor().get_exercises()

        self.assertEqual(result, [])

    @responses.activate
    def test_get_user_information_success(self):
        responses.add(
            responses.GET, f"{BASE_URL}/users/user-1", json={"user-id": "user-1"}, status=200
        )

        result = _extractor().get_user_information()

        self.assertEqual(result, {"user-id": "user-1"})


class TestGetPhysicalInfo(unittest.TestCase):
    TABLE_NAME = "health_metrics_test"

    def setUp(self):
        os.environ["TABLE_NAME"] = self.TABLE_NAME
        self.mock_aws = mock_aws()
        self.mock_aws.start()
        boto3.client("dynamodb", region_name="us-east-1").create_table(
            TableName=self.TABLE_NAME,
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

    def _extractor_with_mocked_accesslink(self):
        extractor = _extractor()
        extractor.accesslink = MagicMock()
        return extractor

    def test_no_new_transaction_falls_back_to_dynamodb_record(self):
        boto3.resource("dynamodb", region_name="us-east-1").Table(self.TABLE_NAME).put_item(
            Item={"uid": "user-1", "date": "2026/01/01", "hrv": 55}
        )
        extractor = self._extractor_with_mocked_accesslink()
        extractor.accesslink.physical_info.create_transaction.return_value = None

        result = extractor.get_physical_info(date=datetime(2026, 1, 1))

        self.assertEqual(result["hrv"], 55)

    def test_new_transaction_commits_and_returns_physical_info(self):
        extractor = self._extractor_with_mocked_accesslink()
        transaction = MagicMock()
        transaction.list_physical_infos.return_value = {
            "physical-informations": ["https://example.com/info/1"]
        }
        transaction.get_physical_info.return_value = {"weight": 80}
        extractor.accesslink.physical_info.create_transaction.return_value = transaction

        result = extractor.get_physical_info(date=datetime(2026, 1, 1))

        transaction.get_physical_info.assert_called_once_with("https://example.com/info/1")
        transaction.commit.assert_called_once()
        self.assertEqual(result, {"weight": 80})

    def test_accesslink_exception_returns_empty_dict(self):
        extractor = self._extractor_with_mocked_accesslink()
        extractor.accesslink.physical_info.create_transaction.side_effect = Exception("API down")

        result = extractor.get_physical_info(date=datetime(2026, 1, 1))

        self.assertEqual(result, {})

    @freeze_time("2026-08-05")
    def test_invalid_date_kwarg_falls_back_to_a_correctly_formatted_todays_date(self):
        # "date" without a .strftime() (e.g. an already-formatted string)
        # hits the inner except and falls back to datetime.now(), formatted
        # the same way as every other branch ("%Y/%m/%d") - seed a record
        # under today's formatted date to prove the fallback actually
        # produces a usable DynamoDB key, not just "doesn't crash".
        boto3.resource("dynamodb", region_name="us-east-1").Table(self.TABLE_NAME).put_item(
            Item={"uid": "user-1", "date": "2026/08/05", "hrv": 61}
        )
        extractor = self._extractor_with_mocked_accesslink()
        extractor.accesslink.physical_info.create_transaction.return_value = None

        result = extractor.get_physical_info(date="not-a-datetime")

        self.assertEqual(result["hrv"], 61)


class TestExtractionDecider(unittest.TestCase):
    @freeze_time("2026-08-03")  # Monday
    def test_monday_looks_back_6_days(self):
        to_date, days = _extractor().extraction_decider()

        self.assertEqual(days, 6)
        self.assertEqual(to_date, datetime(2026, 8, 3) - timedelta(days=1))

    @freeze_time("2026-08-07")  # Friday
    def test_friday_looks_back_3_days(self):
        to_date, days = _extractor().extraction_decider()

        self.assertEqual(days, 3)
        self.assertEqual(to_date, datetime(2026, 8, 7) - timedelta(days=1))

    @freeze_time("2026-08-05")  # Wednesday
    def test_other_weekday_looks_back_0_days(self):
        to_date, days = _extractor().extraction_decider()

        self.assertEqual(days, 0)
        self.assertEqual(to_date, datetime(2026, 8, 5) - timedelta(days=1))


class TestExtractorComposition(unittest.TestCase):
    def test_composes_health_data_from_the_three_dates_given(self):
        extractor = _extractor()
        extractor.get_sleep_for_date = MagicMock(return_value={"sleep": "d1"})
        extractor.get_recharge_for_date = MagicMock(return_value={"recharge": "d1"})
        extractor.get_heartrate_for_date = MagicMock(return_value={"hr": "d2"})
        extractor.get_activities_for_date = MagicMock(return_value={"activity": "d2"})
        extractor.get_physical_info = MagicMock(return_value={"physical": "d3"})

        result = extractor.extractor(date_1="2026-01-02", date_2="2026-01-01", date_3="2025-12-31")

        self.assertIsInstance(result, HealthData)
        extractor.get_sleep_for_date.assert_called_once_with(to_date="2026-01-02")
        extractor.get_recharge_for_date.assert_called_once_with(to_date="2026-01-02")
        extractor.get_heartrate_for_date.assert_called_once_with(to_date="2026-01-01", days=0)
        extractor.get_activities_for_date.assert_called_once_with(to_date="2026-01-01", days=0)
        extractor.get_physical_info.assert_called_once_with(date="2025-12-31")
        self.assertEqual(result.sleep, {"sleep": "d1"})
        self.assertEqual(result.physical_info, {"physical": "d3"})


if __name__ == "__main__":
    unittest.main()
