import statistics
import unittest
from datetime import datetime, timedelta

import pandas as pd
from exercise_insights.core.transform.health import Health
from exercise_insights.core.transform.helpers import Helpers


def _daily_records(hrv_values, end_date):
    """Build one health record per day, most recent = end_date, oldest first."""
    records = []
    start = end_date - timedelta(days=len(hrv_values) - 1)
    for offset, hrv in enumerate(hrv_values):
        date = start + timedelta(days=offset)
        records.append(
            {
                "date": date.strftime("%Y/%m/%d"),
                "hrv": hrv,
                "activity_score": 30.0,
                "average_daily_hr": 70,
                "dhrps": 0.0008,
                "total_sleep": 420,
                "steps": 8000,
                "ans_charge": 1.0,
            }
        )
    return records


class TestHealthEmptyInput(unittest.TestCase):
    def test_empty_response_leaves_instance_without_response_set(self):
        health = Health([])
        # __init__ returns early on falsy input, same guard as Exercise's.
        self.assertFalse(hasattr(health, "response"))


class TestHelperHealthMetrics(unittest.TestCase):
    END = datetime(2026, 1, 1)

    def test_fewer_than_10_rows_returns_none(self):
        data = _daily_records([40] * 9, self.END)
        result = Health(data).health_summary()
        self.assertIsNone(result["hrv"])

    def test_column_absent_from_schema_returns_none(self):
        # health_summary() pre-declares a fixed set of columns (activity_score,
        # hrv, etc.), so deleting a key from every record doesn't actually
        # remove that column - it stays present, just all-NaN (see the next
        # test). The "column not in df.columns" guard only ever fires for a
        # column outside that pre-declared set entirely.
        data = _daily_records([40] * 12, self.END)
        health = Health(data)
        # Build the same shape of dataframe health_summary() builds
        # internally, to call the guarded helper directly with a genuinely
        # unknown column.
        normalised = Helpers().helper_decimal_to_native(data)
        df = Helpers().helper_add_data_dataframe(
            df=pd.DataFrame(columns=["date", "hrv"]), data=normalised, date_format="%Y/%m/%d"
        )
        self.assertIsNone(health.helper_health_metrics(df=df, column="totally_unknown_metric"))

    def test_declared_column_with_no_real_values_returns_nan_not_none(self):
        # Documents the flip side of the above: dhrps IS pre-declared, so
        # even with every record missing it, the guard doesn't catch it -
        # health_summary() returns a dict of NaNs instead of None.
        data = _daily_records([40] * 12, self.END)
        for record in data:
            del record["dhrps"]

        result = Health(data).health_summary()["dhrps"]

        self.assertIsNotNone(result)
        self.assertNotEqual(result["mean_7d"], result["mean_7d"])  # NaN != NaN

    def test_mean_7d_and_baseline_28d_match_independent_calculation(self):
        # 5 older days at 40, then the most recent 7 days at 50.
        hrv_values = [40] * 5 + [50] * 7
        data = _daily_records(hrv_values, self.END)

        result = Health(data).health_summary()["hrv"]

        # Independently derive the 7d window with the same >= (latest - 7
        # days) boundary the source uses - that's an 8-calendar-day
        # inclusive window, not "the last 7 list items".
        dated_values = [(datetime.strptime(r["date"], "%Y/%m/%d"), r["hrv"]) for r in data]
        window_start_7d = self.END - timedelta(days=7)
        values_7d = [v for d, v in dated_values if d >= window_start_7d]

        expected_mean_7d = statistics.mean(values_7d)
        expected_baseline_28d = statistics.mean(hrv_values)
        expected_std_28d = statistics.stdev(hrv_values)

        self.assertAlmostEqual(result["mean_7d"], expected_mean_7d, places=6)
        self.assertAlmostEqual(result["baseline_28d"], expected_baseline_28d, places=6)
        self.assertAlmostEqual(result["std_dev_28d"], expected_std_28d, places=6)
        self.assertAlmostEqual(
            result["z_score_7d_vs_28d"],
            (expected_mean_7d - expected_baseline_28d) / expected_std_28d,
            places=6,
        )

    def test_zero_variance_gives_zero_z_score_not_a_division_error(self):
        # All 12 days identical -> std_dev_28d is 0, which would divide-by-zero
        # if not guarded.
        data = _daily_records([45] * 12, self.END)

        result = Health(data).health_summary()["hrv"]

        self.assertEqual(result["std_dev_28d"], 0)
        self.assertEqual(result["z_score_7d_vs_28d"], 0)

    def test_sample_size_and_completeness_ratio_reflect_90d_window(self):
        data = _daily_records([45] * 12, self.END)

        result = Health(data).health_summary()["hrv"]

        self.assertEqual(result["sample_size"], 12)
        self.assertEqual(result["completeness_ratio"], round(12 / 90, 3))

    def test_ans_charge_is_actually_computed(self):
        # ans_charge isn't in health_summary()'s base column_names list, but
        # every record includes it - confirms it still ends up as a usable
        # column via pandas' concat (which unions columns from the incoming
        # data), not silently dropped.
        data = _daily_records([45] * 12, self.END)

        result = Health(data).health_summary()["ans_charge"]

        self.assertIsNotNone(result)
        self.assertEqual(result["mean_7d"], 1.0)


if __name__ == "__main__":
    unittest.main()
