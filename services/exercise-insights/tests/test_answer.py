import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

import boto3
import httpx
import respx
from exercise_insights.core.answer import answer_question, get_exercise_metrics, get_weekly_actuals
from moto import mock_aws
from openai import APIStatusError


def _midnight(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"


def _response_body(text: str) -> dict:
    return {
        "id": "resp_test123",
        "created_at": 1735000000,
        "model": "gpt-5-mini",
        "object": "response",
        "output": [
            {
                "id": "msg_test123",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            }
        ],
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
    }


class TestAnswerQuestion(unittest.TestCase):
    def setUp(self):
        self.config_patcher = patch("exercise_insights.core.answer.config_loader")
        mock_config_loader = self.config_patcher.start()
        mock_config_loader.return_value = {"OPEN_AI_AUTH": "test-key"}

        self.prompt_patcher = patch("exercise_insights.core.answer.get_prompt")
        self.prompt_patcher.start().return_value = "You are a running coach."

        self.extract_patcher = patch("exercise_insights.core.answer.dynamo_extract")
        mock_extract_cls = self.extract_patcher.start()
        mock_extract_cls.return_value.get_records_bt_dates.return_value = []

        self.exercise_patcher = patch("exercise_insights.core.answer.Exercise")
        mock_exercise_cls = self.exercise_patcher.start()
        mock_exercise_cls.return_value.exercise_summary.return_value = {"training_load": "moderate"}

    def tearDown(self):
        self.config_patcher.stop()
        self.prompt_patcher.stop()
        self.extract_patcher.stop()
        self.exercise_patcher.stop()

    @respx.mock
    def test_given_200_response_then_output_text_returned(self):
        respx.post(OPENAI_RESPONSES_URL).mock(
            return_value=httpx.Response(200, json=_response_body("You ran 3 times this week."))
        )

        result = answer_question(user_id="user-1", question="How did I do this week?")

        self.assertEqual(result, "You ran 3 times this week.")

    @respx.mock
    def test_given_500_response_then_raises_and_logs(self):
        respx.post(OPENAI_RESPONSES_URL).mock(
            return_value=httpx.Response(
                500, json={"error": {"message": "internal error", "type": "server_error"}}
            )
        )

        with self.assertLogs(level="ERROR") as log, self.assertRaises(APIStatusError):
            answer_question(user_id="user-1", question="How did I do this week?")

        self.assertIn("Error raising prompt with OpenAI", "".join(log.output))


class TestGetExerciseMetrics(unittest.TestCase):
    def setUp(self):
        self.extract_patcher = patch("exercise_insights.core.answer.dynamo_extract")
        self.mock_extract_cls = self.extract_patcher.start()
        self.mock_extract_cls.return_value.get_records_bt_dates.return_value = [
            {"uid": "user-1", "date": "2026-08-01"}
        ]

        self.exercise_patcher = patch("exercise_insights.core.answer.Exercise")
        self.mock_exercise_cls = self.exercise_patcher.start()
        self.mock_exercise_cls.return_value.exercise_summary.return_value = {
            "training_load": {"7d": {"total_distance_miles": 20}}
        }

    def tearDown(self):
        self.extract_patcher.stop()
        self.exercise_patcher.stop()

    def test_queries_exercise_data_table_and_returns_summary(self):
        result = get_exercise_metrics(user_id="user-1")

        self.mock_extract_cls.assert_called_once_with(table="exercise_data")
        self.mock_extract_cls.return_value.get_records_bt_dates.assert_called_once()
        call_kwargs = self.mock_extract_cls.return_value.get_records_bt_dates.call_args.kwargs
        self.assertEqual(call_kwargs["uid"], "user-1")
        self.mock_exercise_cls.assert_called_once_with(
            self.mock_extract_cls.return_value.get_records_bt_dates.return_value
        )
        self.assertEqual(result, {"training_load": {"7d": {"total_distance_miles": 20}}})

    def test_respects_custom_days_window(self):
        get_exercise_metrics(user_id="user-1", days=28)

        call_kwargs = self.mock_extract_cls.return_value.get_records_bt_dates.call_args.kwargs
        start = call_kwargs["start_date"]
        end = call_kwargs["end_date"]
        self.assertNotEqual(start, end)


class TestGetExerciseMetricsRealQuery(unittest.TestCase):
    """The mocked TestGetExerciseMetrics class above mocks dynamo_extract
    entirely, so it never exercises the real date-range query -- it could
    not have caught a real production bug: the query's date format
    ("%Y/%m/%d") didn't match what exercise-etl actually writes
    (load_creator.py: a raw Polar "%Y-%m-%dT%H:%M:%S" timestamp), so
    DynamoDB's lexicographic string BETWEEN silently matched zero real
    records, for any date range, on any account. Real moto-backed table
    here, not mocked, so this test would have caught it."""

    def setUp(self):
        self.mock_aws = mock_aws()
        self.mock_aws.start()
        table = boto3.resource("dynamodb", region_name="us-east-1").create_table(
            TableName="exercise_data",
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
        table.wait_until_exists()
        self.table = table

    def tearDown(self):
        self.mock_aws.stop()

    def test_finds_a_record_stored_in_exercise_etls_real_write_format(self):
        # date matches load_creator.py's real write format exactly: a raw
        # Polar Accesslink start_time, e.g. "2026-02-22T07:50:17".
        stored_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%S")
        self.table.put_item(
            Item={
                "uid": "user-1",
                "date": stored_date,
                "sport": "RUNNING",
                "distance": 5,
                "durationSec": 3600,
                "cardioLoad": 50,
                "averageHeartRate": 140,
                "HRDrift": 3,
                "HRZones": {"Zone 1": 10, "Zone 2": 20, "Zone 3": 15, "Zone 4": 5, "Recovery": 5},
                "paceVariability": 2,
                "efficiencyFactor": 1,
            }
        )

        result = get_exercise_metrics(user_id="user-1")

        self.assertEqual(result["validity_metrics"]["7d_sample_days"], 1)
        self.assertEqual(result["training_load"]["7d"]["runs"], 1)

    def test_genuinely_no_records_returns_a_graceful_summary_not_a_crash(self):
        # A real DynamoDB Query with no matches (a brand-new user, or a
        # window with no exercise) -- Query's Items is always [], never
        # None. Regression test for a real production AttributeError: this
        # used to crash before Exercise.__init__ was fixed.
        result = get_exercise_metrics(user_id="user-with-no-data")

        self.assertEqual(result["validity_metrics"]["7d_sample_days"], 0)
        self.assertEqual(result["training_load"], {"7d": {}, "28d": {}, "90d": {}})

    def test_elevation_gain_and_descent_survive_a_real_dynamodb_round_trip(self):
        # elevation_ascent/elevation_descent are written by exercise-etl's
        # load_creator.py as plain ints (not Decimal, unlike most other
        # numeric fields) -- a real moto table, not a mocked
        # dynamo_extract, is what actually proves that round-trips cleanly
        # through DynamoDB's number type and Helpers.helper_decimal_to_native.
        stored_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%S")
        self.table.put_item(
            Item={
                "uid": "user-1",
                "date": stored_date,
                "sport": "RUNNING",
                "distance": 5,
                "durationSec": 3600,
                "cardioLoad": 50,
                "averageHeartRate": 140,
                "elevation_ascent": 1200,
                "elevation_descent": 1150,
            }
        )

        result = get_exercise_metrics(user_id="user-1")

        self.assertEqual(result["training_load"]["7d"]["total_elevation_gain_ft"], 1200)
        self.assertEqual(result["training_load"]["7d"]["total_elevation_descent_ft"], 1150)
        self.assertEqual(result["training_load"]["7d"]["elevation_gain_ft_per_mile"], 240.0)
        self.assertEqual(result["training_load"]["7d"]["elevation_descent_ft_per_mile"], 230.0)
        self.assertEqual(result["long_run_metrics"]["7d"]["gain_ft"], 1200)
        self.assertEqual(result["long_run_metrics"]["7d"]["descent_ft"], 1150)
        self.assertEqual(result["long_run_metrics"]["7d"]["gain_ft_per_mile"], 240.0)

    def test_long_run_history_survives_a_real_dynamodb_round_trip(self):
        # sort_values (not nlargest) is what makes this work at all: the
        # "distance" column comes through as object dtype from a real
        # moto-backed round trip (helper_add_data_dataframe builds the
        # frame from per-row pd.Series), which nlargest rejects outright --
        # confirmed live, this test caught that real bug during development.
        for day_offset, distance in enumerate([12, 8, 15], start=1):
            self.table.put_item(
                Item={
                    "uid": "user-1",
                    "date": (datetime.now() - timedelta(days=day_offset)).strftime(
                        "%Y-%m-%dT%H:%M:%S"
                    ),
                    "sport": "RUNNING",
                    "distance": distance,
                    "durationSec": 3600 * 3,
                    "cardioLoad": 120,
                    "averageHeartRate": 145,
                    "elevation_ascent": distance * 100,
                    "elevation_descent": distance * 90,
                }
            )

        result = get_exercise_metrics(user_id="user-1")

        history = result["long_run_history"]
        self.assertEqual(len(history), 3)
        self.assertEqual([entry["distance"] for entry in history], [15.0, 12.0, 8.0])
        self.assertEqual(history[0]["gain_ft"], 1500)
        self.assertEqual(history[0]["gain_ft_per_mile"], 100.0)
        self.assertIsNone(history[0]["terrain"])


class TestGetWeeklyActuals(unittest.TestCase):
    """Real moto-backed table, same pattern TestGetExerciseMetricsRealQuery
    establishes -- this bucketing logic is a raw per-record loop over the
    same query get_exercise_metrics uses, so it needs the same real-query
    coverage to catch a real date-format mismatch, not a mocked
    dynamo_extract that would hide one."""

    def setUp(self):
        self.mock_aws = mock_aws()
        self.mock_aws.start()
        table = boto3.resource("dynamodb", region_name="us-east-1").create_table(
            TableName="exercise_data",
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
        table.wait_until_exists()
        self.table = table

    def tearDown(self):
        self.mock_aws.stop()

    def test_buckets_a_record_into_the_correct_week(self):
        plan_start = _midnight(datetime.now() - timedelta(days=10))
        record_date = (plan_start + timedelta(days=8, hours=6)).strftime("%Y-%m-%dT%H:%M:%S")
        self.table.put_item(
            Item={
                "uid": "user-1",
                "date": record_date,
                "sport": "RUNNING",
                "distance": 5,
                "durationSec": 3600,
                "elevation_ascent": 500,
            }
        )

        result = get_weekly_actuals("user-1", plan_start.strftime("%Y-%m-%d"), weeks=2)

        self.assertEqual(result[0]["actual_distance_miles"], 0.0)  # week 0: no records
        self.assertEqual(result[1]["actual_distance_miles"], 5)
        self.assertEqual(result[1]["actual_duration_hr"], 1.0)
        self.assertEqual(result[1]["actual_elevation_gain_ft"], 500)

    def test_non_running_sport_is_excluded(self):
        plan_start = _midnight(datetime.now() - timedelta(days=10))
        record_date = (plan_start + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
        self.table.put_item(
            Item={"uid": "user-1", "date": record_date, "sport": "CYCLING", "distance": 20, "durationSec": 3600}
        )

        result = get_weekly_actuals("user-1", plan_start.strftime("%Y-%m-%d"), weeks=2)

        self.assertEqual(result[0]["actual_distance_miles"], 0.0)

    def test_multiple_records_in_the_same_week_are_summed(self):
        plan_start = _midnight(datetime.now() - timedelta(days=10))
        for offset in (1, 2):
            record_date = (plan_start + timedelta(days=offset)).strftime("%Y-%m-%dT%H:%M:%S")
            self.table.put_item(
                Item={
                    "uid": "user-1",
                    "date": record_date,
                    "sport": "RUNNING",
                    "distance": 5,
                    "durationSec": 3600,
                    "elevation_ascent": 300,
                }
            )

        result = get_weekly_actuals("user-1", plan_start.strftime("%Y-%m-%d"), weeks=2)

        self.assertEqual(result[0]["actual_distance_miles"], 10)
        self.assertEqual(result[0]["actual_duration_hr"], 2.0)
        self.assertEqual(result[0]["actual_elevation_gain_ft"], 600)

    def test_genuinely_no_records_returns_zeros_for_already_started_weeks(self):
        plan_start = _midnight(datetime.now() - timedelta(days=10))

        result = get_weekly_actuals("user-with-no-data", plan_start.strftime("%Y-%m-%d"), weeks=2)

        self.assertEqual(
            result,
            [
                {"actual_distance_miles": 0.0, "actual_duration_hr": 0.0, "actual_elevation_gain_ft": 0.0},
                {"actual_distance_miles": 0.0, "actual_duration_hr": 0.0, "actual_elevation_gain_ft": 0.0},
            ],
        )

    def test_a_week_that_has_not_started_yet_gets_none_not_zero(self):
        plan_start = _midnight(datetime.now())

        result = get_weekly_actuals("user-with-no-data", plan_start.strftime("%Y-%m-%d"), weeks=3)

        self.assertEqual(result[0]["actual_distance_miles"], 0.0)  # week 0 starts today
        self.assertIsNone(result[2]["actual_distance_miles"])  # week 2 starts 14 days from now
        self.assertIsNone(result[2]["actual_duration_hr"])
        self.assertIsNone(result[2]["actual_elevation_gain_ft"])


if __name__ == "__main__":
    unittest.main()
