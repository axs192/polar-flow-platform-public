import unittest
from unittest.mock import patch

from freezegun import freeze_time
from src.app.messaging.create_message import Create_Message
from src.app.messaging.response_templates import (
    template_weekend,
)


class TestNotifications(unittest.TestCase):
    def setUp(self):
        self.metrics = {
            "Total_Steps": 52000,
            "No_Data": 0,
            "Total_Goal": 56000,
            "Daily_Goal": 8000,
            "Average_Steps": 7500.5,
        }

        self.no_recommendations = {
            "Total_Steps": 56000,
            "No_Data": 0,
            "Total_Goal": 56000,
            "Daily_Goal": 8000,
            "Average_Steps": 8000.5,
        }

        self.multiple_suggestions = {
            "Total_Steps": 56000,
            "No_Data": 0,
            "Total_Goal": 70000,
            "Daily_Goal": 12000,
            "Average_Steps": 7500.5,
        }

        self.no_data = {
            "No_Data": 1,
        }

        self.notifier = Create_Message(self.metrics)

        self.no_notifier = Create_Message(self.no_data)

    def test_no_data_message(self):
        with patch.object(self.no_notifier, "sync_activities", return_value="SYNC") as mock_sync:
            result = self.no_notifier.create_message()
            self.assertEqual(result, "SYNC")
            mock_sync.assert_called_once()

    @freeze_time("2025-09-20 09:00:00")
    def test_generate_daily_message(self):
        with patch.object(
            self.notifier, "generate_daily_response", return_value="DAILY"
        ) as mock_daily:
            result = self.notifier.create_message()
            self.assertEqual(result, "DAILY")
            mock_daily.assert_called_once()

    @freeze_time("2025-09-19 09:00:00")
    def test_friday_message_no_suggestions(self):
        result, message = Create_Message(self.no_recommendations).create_message()
        self.assertEqual(message, "On Track for the weekend")

    @freeze_time("2025-09-19 09:00:00")
    def test_friday_message_suggestions(self):
        result, messsage = self.notifier.create_message()
        self.assertEqual(messsage, "Get ready for the weekend")

    @freeze_time("2025-09-22 09:00:00")
    def test_weekly_review_message(self):
        with patch.object(
            self.notifier, "generate_weekly_review", return_value="WEEKLY"
        ) as mock_weekly:
            result = self.notifier.create_message()
            self.assertEqual(result, "WEEKLY")
            mock_weekly.assert_called_once()

    def test_number_suggestions(self):
        # Call the method
        template_response = template_weekend.substitute(
            week_steps=1000, daily_remaining=1000, suggestions="Do Nothing"
        )
        standard_lines = len(template_response.split("\n"))
        result = Create_Message(self.multiple_suggestions).generate_weekend_response()
        result_lines = len(result[0].split("\n"))

        self.assertGreater(result_lines, standard_lines)
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)

    def test_generate_daily_response_returns_two(self):
        result = self.notifier.generate_daily_response()
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)

    def test_generate_weekend_response_returns_two(self):
        result = self.notifier.generate_weekend_response()
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)

    def test_generate_weekly_review_returns_two(self):
        result = self.notifier.generate_weekly_review()
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)

    def test_error_message_returns_two(self):
        result = self.notifier.error_message()
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)

    def test_sync_activities_returns_two(self):
        result = self.notifier.sync_activities()
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)


if __name__ == "__main__":
    unittest.main()
