import unittest
from unittest.mock import patch

import boto3
from moto import mock_aws
from src import context_store, tools
from src.config import settings


class ToolsTestCase(unittest.TestCase):
    def setUp(self):
        self.mock_aws = mock_aws()
        self.mock_aws.start()
        settings.context_bucket = "test-context-bucket"
        settings.polar_user_id = "polar-user-1"
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=settings.context_bucket)
        context_store._s3_client = None
        self.user_token = context_store.current_user_id.set("web-user-1")

    def tearDown(self):
        context_store.current_user_id.reset(self.user_token)
        context_store._s3_client = None
        self.mock_aws.stop()


class TestGetMyTrainingData(ToolsTestCase):
    @patch("exercise_insights.core.get_exercise_metrics")
    def test_fetches_and_caches_on_first_call(self, mock_get_metrics):
        mock_get_metrics.return_value = {"training_load": {"7d": 10}}

        result = tools.get_my_training_data()

        mock_get_metrics.assert_called_once_with("polar-user-1")
        self.assertEqual(result, {"training_load": {"7d": 10}})
        self.assertEqual(context_store.get_cached_training_data("web-user-1"), result)

    @patch("exercise_insights.core.get_exercise_metrics")
    def test_second_call_same_day_reuses_cache_without_refetching(self, mock_get_metrics):
        mock_get_metrics.return_value = {"training_load": {"7d": 10}}
        tools.get_my_training_data()

        mock_get_metrics.reset_mock()
        result = tools.get_my_training_data()

        mock_get_metrics.assert_not_called()
        self.assertEqual(result, {"training_load": {"7d": 10}})

    @patch("exercise_insights.core.get_exercise_metrics")
    def test_force_refresh_bypasses_cache(self, mock_get_metrics):
        mock_get_metrics.return_value = {"training_load": {"7d": 10}}
        tools.get_my_training_data()

        mock_get_metrics.return_value = {"training_load": {"7d": 20}}
        result = tools.get_my_training_data(force_refresh=True)

        self.assertEqual(mock_get_metrics.call_count, 2)
        self.assertEqual(result, {"training_load": {"7d": 20}})

    @patch("exercise_insights.core.get_exercise_metrics")
    def test_no_exercise_data_yet_is_cached_and_returned_cleanly(self, mock_get_metrics):
        # get_exercise_metrics' real "no data in range" shape (see
        # exercise-insights' own tests for the fix that made this graceful
        # instead of raising AttributeError) -- this end of the seam just
        # needs to confirm the tool/S3-cache layer handles it like any
        # other result, not that exercise-insights itself is correct.
        mock_get_metrics.return_value = {
            "training_load": {"7d": {}, "28d": {}, "90d": {}},
            "validity_metrics": {"90d_sample_days": 0, "28d_sample_days": 0, "7d_sample_days": 0},
        }

        result = tools.get_my_training_data()

        self.assertEqual(result["validity_metrics"]["7d_sample_days"], 0)
        self.assertEqual(context_store.get_cached_training_data("web-user-1"), result)


class TestSaveAthleteProfile(ToolsTestCase):
    def test_saves_and_returns_profile(self):
        result = tools.save_athlete_profile(sport="running", goal="75km ultra")

        self.assertEqual(result["sport"], "running")
        self.assertEqual(context_store.get_profile("web-user-1")["goal"], "75km ultra")

    def test_upsert_overwrites_previous_profile(self):
        tools.save_athlete_profile(sport="running", goal="75km ultra")

        tools.save_athlete_profile(sport="running", goal="100km ultra")

        self.assertEqual(context_store.get_profile("web-user-1")["goal"], "100km ultra")

    def test_saves_communication_style_separately_from_training_preferences(self):
        tools.save_athlete_profile(
            sport="running",
            goal="75km ultra",
            training_preferences="periodized structure",
            communication_style="brief and blunt",
        )

        profile = context_store.get_profile("web-user-1")
        self.assertEqual(profile["training_preferences"], "periodized structure")
        self.assertEqual(profile["communication_style"], "brief and blunt")


class TestSaveTrainingPlan(ToolsTestCase):
    def _weeks(self, n=2):
        return [
            {"planned_distance_miles": 30 + i, "planned_duration_hr": 4.0, "planned_elevation_gain_ft": 1500}
            for i in range(n)
        ]

    def test_saves_and_returns_plan(self):
        result = tools.save_training_plan(start_date="2026-08-10", weeks=self._weeks())

        self.assertEqual(result["start_date"], "2026-08-10")
        self.assertEqual(len(result["weeks"]), 2)
        self.assertEqual(context_store.get_plan("web-user-1")["start_date"], "2026-08-10")

    def test_saves_themes_with_non_contiguous_weeks(self):
        result = tools.save_training_plan(
            start_date="2026-08-10",
            weeks=self._weeks(3),
            themes=[{"label": "Down week", "weeks": [0, 2], "color": "#3987e5"}],
        )

        self.assertEqual(result["themes"][0]["weeks"], [0, 2])

    def test_upsert_overwrites_previous_plan(self):
        tools.save_training_plan(start_date="2026-08-10", weeks=self._weeks(2))

        tools.save_training_plan(start_date="2026-09-01", weeks=self._weeks(4))

        plan = context_store.get_plan("web-user-1")
        self.assertEqual(plan["start_date"], "2026-09-01")
        self.assertEqual(len(plan["weeks"]), 4)

    def test_theme_week_out_of_range_returns_error_not_raise(self):
        result = tools.save_training_plan(
            start_date="2026-08-10",
            weeks=self._weeks(2),
            themes=[{"label": "Bad theme", "weeks": [5], "color": "#3987e5"}],
        )

        self.assertIn("error", result)
        self.assertIsNone(context_store.get_plan("web-user-1"))

    def test_invalid_color_returns_error_not_raise(self):
        result = tools.save_training_plan(
            start_date="2026-08-10",
            weeks=self._weeks(1),
            themes=[{"label": "Bad color", "weeks": [0], "color": "blue"}],
        )

        self.assertIn("error", result)

    def test_no_weeks_returns_error_not_raise(self):
        result = tools.save_training_plan(start_date="2026-08-10", weeks=[])

        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
