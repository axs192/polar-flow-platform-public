import unittest
from datetime import datetime
from decimal import Decimal
from unittest.mock import patch

from src.app.ETL.extractor import HealthData
from src.app.ETL.transform import Transform
from src.data.loader import load_json


class TestTransform(unittest.TestCase):
    def setUp(self):
        self.sample_data = load_json("4_day_sample.json")
        self.one_day_data = load_json("1_day_sample.json")
        self.nightly_recharge = load_json("recharge_sample.json")
        self.heart_rate = load_json("heart_rate_sample.json")
        self.sleep_sample = load_json("sleep_sample.json")
        self.full_sample: HealthData = load_json("health_extraction.json")

    def test_no_data_provided(self):
        with patch("src.app.ETL.transform.logging") as mock_logging:
            transform = Transform(None)
            mock_logging.error.assert_called_with("No data provided.")
            self.assertFalse(hasattr(transform, "response"))

    def test_date_conversion_positive(self):
        transform = Transform(self.sample_data)
        result = transform.date_conversion("2025-09-07T12:36")
        self.assertEqual(result, "09/07/25")  # mm/dd/yy format

    def test_date_conversion_negative(self):
        transform = Transform(self.sample_data)
        with patch("src.app.ETL.transform.logging") as mock_logging:
            result = transform.date_conversion("invalid-date")
            self.assertIsNone(result)
            mock_logging.warning.assert_called()

    def test_create_metrics_positive(self):
        transform = Transform(self.sample_data, start_date="2025-09-10").create_metrics()
        self.assertEqual(transform["Most_Steps"], 11576.0)

    def test_total_sleep(self):
        transform = Transform(self.sleep_sample).daily_sleep()
        self.assertEqual(transform, 3000)

    def test_create_metrics_1_day_response(self):
        transform = Transform(self.one_day_data, start_date="2025-09-10").create_metrics()
        self.assertEqual(transform["Most_Steps"], 4050.0)

    def test_extract_averageHR(self):
        transform = Transform(self.heart_rate).calculate_average_hr()
        self.assertEqual(transform, Decimal("62.3"))

    def test_maxHR(self):
        transform = Transform(self.full_sample["heart_rate"]["heart_rates"][0]).calculate_maxHR()
        self.assertEqual(transform, 169)

    def test_minHR(self):
        transform = Transform(self.heart_rate).calculate_minHR()
        self.assertEqual(transform, 62)

    def test_calculate_activity(self):
        transform = Transform(self.heart_rate).calculate_exercise_brackets()
        self.assertEqual(transform["moderate_activity"], 0.0)

    def test_metrics_datetime_format(self):
        start_date = datetime(2025, 9, 10)
        transform = Transform(self.sample_data, start_date=start_date).create_metrics()
        self.assertEqual(transform["Most_Steps"], 11576.0)

    def test_metrics_day_argument(self):
        start_date = datetime(2025, 9, 10)
        transform = Transform(self.sample_data, start_date=start_date, days=0).create_metrics()
        self.assertEqual(transform["Most_Steps"], 4050.0)

    def test_no_steps_available_for_date(self):
        start_date = datetime(2026, 9, 10)
        transform = Transform(self.sample_data, start_date=start_date, days=0).create_metrics()
        self.assertEqual(transform["No_Data"], 1.0)

    # TODO: Add tests that handles corrupted data, probably on date and steps

    @patch("src.app.ETL.transform.Transform.date_conversion")
    def test_create_metrics_negative(self, mock_date_conversion):
        with patch("src.app.ETL.transform.logging"):
            mock_date_conversion.return_value = None
            transform = Transform(self.sample_data)
            with self.assertRaises(ValueError) as context:
                transform.create_metrics()
            self.assertIn("No steps data found", str(context.exception))


if __name__ == "__main__":
    unittest.main()
