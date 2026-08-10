import json
import unittest

from exercise_insights.core.transform.exercise import Exercise


def _run(date, distance=5.0, duration_hr=1.0, cardio_load=50.0, avg_hr=140, **overrides):
    """Build one RUNNING record shaped like exercise-etl's load_creator.create_load() output."""
    record = {
        "date": date,
        "sport": "RUNNING",
        "distance": distance,
        "durationSec": duration_hr * 3600,
        "cardioLoad": cardio_load,
        "averageHeartRate": avg_hr,
        "HRDrift": 3.0,
        "HRZones": {"Recovery": 5.0, "Zone 1": 10.0, "Zone 2": 20.0, "Zone 3": 15.0, "Zone 4": 5.0},
        "paceVariability": 2.0,
        "efficiencyFactor": 0.08,
        "runningIndex": 45,
    }
    record.update(overrides)
    return record


class TestExerciseEmptyInput(unittest.TestCase):
    # Regression tests for a real production AttributeError: 'Exercise'
    # object has no attribute 'running_df', hit whenever a user has zero
    # exercise records in the queried window (a real, common DynamoDB Query
    # result, not just a hand-wavy edge case) -- get_exercise_metrics()
    # calls exercise_summary() unconditionally, so this crashed both the
    # WhatsApp Q&A path and the web app's get_my_training_data tool.

    def test_empty_response_leaves_working_empty_dataframes(self):
        exercise = Exercise([])

        self.assertTrue(hasattr(exercise, "running_df"))
        self.assertTrue(exercise.running_df.empty)

    def test_empty_response_summary_does_not_raise_and_is_json_safe(self):
        # The exact call get_exercise_metrics() makes -- the direct
        # regression test for the live bug.
        summary = Exercise([]).exercise_summary()

        # Must round-trip through JSON cleanly (this becomes a tool result
        # sent to the LLM) -- NaN isn't valid JSON, so a stray NaN here
        # would be a real, separate bug even though json.dumps happens not
        # to raise on it by default.
        reparsed = json.loads(json.dumps(summary))
        self.assertEqual(reparsed["training_load"], {"7d": {}, "28d": {}, "90d": {}})
        self.assertEqual(reparsed["validity_metrics"], {"90d_sample_days": 0, "28d_sample_days": 0, "7d_sample_days": 0})
        self.assertIsNone(reparsed["trend_analysis"]["weekly_distance_trend"])
        self.assertIsNone(reparsed["trend_analysis"]["long_run_trend"])
        self.assertIsNone(reparsed["load_management"]["acute_chronic_load_ratio"])

    def test_empty_response_training_load_returns_empty_periods(self):
        result = Exercise([]).training_load()

        self.assertEqual(result, {"7d": {}, "28d": {}, "90d": {}})

    def test_empty_response_weekly_distance_trend_returns_none(self):
        # .sum()-based (0 for empty data) -- already the safer of the two
        # trend methods, but worth pinning down explicitly.
        self.assertIsNone(Exercise([]).weekly_distance_trend())

    def test_empty_response_long_run_trend_returns_none_not_nan(self):
        # .max()-based: returns NaN (not 0) for empty data, which the
        # original `if baseline == 0` guard didn't catch -- confirmed live,
        # this returned a literal NaN instead of None before the fix.
        self.assertIsNone(Exercise([]).long_run_trend())

    def test_malformed_date_raises_the_real_error_not_a_typeerror(self):
        # create_running_dataframes' except block used to swallow the real
        # exception and implicitly return None, breaking the __init__
        # tuple-unpack with an unrelated "cannot unpack non-iterable
        # NoneType object" TypeError instead of this ValueError.
        bad_record = _run("not-a-date")

        with self.assertRaises(ValueError):
            Exercise([bad_record])


class TestTrainingLoad(unittest.TestCase):
    def test_totals_over_7_days(self):
        data = [
            _run("2026-01-01T08:00:00", distance=5.0, duration_hr=1.0, cardio_load=50.0),
            _run("2026-01-05T08:00:00", distance=3.0, duration_hr=0.5, cardio_load=30.0),
        ]
        result = Exercise(data).training_load()

        self.assertEqual(result["7d"]["total_distance_miles"], 8.0)
        self.assertEqual(result["7d"]["total_duration_hr"], 1.5)
        self.assertEqual(result["7d"]["total_cardio_load"], 80.0)
        self.assertEqual(result["7d"]["runs"], 2)
        self.assertEqual(result["7d"]["longest_run_miles"], 5.0)

    def test_weekly_averages_over_28_days(self):
        # 4 runs of 7 miles each, spread across the 28-day window -> 28 miles / 4 weeks = 7/week.
        data = [
            _run("2025-12-05T08:00:00", distance=7.0, cardio_load=70.0),
            _run("2025-12-12T08:00:00", distance=7.0, cardio_load=70.0),
            _run("2025-12-19T08:00:00", distance=7.0, cardio_load=70.0),
            _run("2026-01-01T08:00:00", distance=7.0, cardio_load=70.0),
        ]
        result = Exercise(data).training_load()

        self.assertEqual(result["28d"]["avg_weekly_distance_miles"], 7.0)
        self.assertEqual(result["28d"]["avg_weekly_cardio_load"], 70.0)
        self.assertEqual(result["28d"]["runs_per_week"], 1.0)
        self.assertEqual(result["28d"]["longest_run_miles"], 7.0)

    def test_excludes_non_running_sports(self):
        data = [
            _run("2026-01-01T08:00:00", distance=5.0),
            _run("2026-01-01T09:00:00", distance=100.0, sport="CYCLING"),
        ]
        result = Exercise(data).training_load()

        self.assertEqual(result["7d"]["total_distance_miles"], 5.0)

    def test_excludes_runs_older_than_90_days(self):
        data = [
            _run("2026-01-01T08:00:00", distance=5.0),
            _run("2025-09-01T08:00:00", distance=999.0),  # >90 days before 2026-01-01
        ]
        result = Exercise(data).training_load()

        # 90d is a "weekly" period (see _calculate_training_load_period),
        # so it reports avg_weekly_distance_miles, not total_distance_miles.
        self.assertEqual(result["90d"]["avg_weekly_distance_miles"], round(5.0 / (90 / 7), 1))


class TestElevationTotals(unittest.TestCase):
    def test_gain_and_descent_are_summed_over_7_days(self):
        data = [
            _run("2026-01-01T08:00:00", elevation_ascent=800, elevation_descent=750),
            _run("2026-01-05T08:00:00", elevation_ascent=200, elevation_descent=150),
        ]
        result = Exercise(data).training_load()

        self.assertEqual(result["7d"]["total_elevation_gain_ft"], 1000)
        self.assertEqual(result["7d"]["total_elevation_descent_ft"], 900)

    def test_gain_and_descent_are_cumulative_totals_not_weekly_averages_over_28_days(self):
        # Unlike avg_weekly_distance_miles etc, elevation is reported as a
        # plain total in the "weekly" branch too -- vert accumulation
        # toward a fixed goal is a total, not a rate.
        data = [
            _run("2025-12-05T08:00:00", elevation_ascent=500, elevation_descent=400),
            _run("2025-12-19T08:00:00", elevation_ascent=500, elevation_descent=400),
        ]
        result = Exercise(data).training_load()

        self.assertEqual(result["28d"]["total_elevation_gain_ft"], 1000)
        self.assertEqual(result["28d"]["total_elevation_descent_ft"], 800)

    def test_absent_when_no_record_has_the_field(self):
        # _run()'s default record has no elevation_ascent/elevation_descent
        # key at all (records predating elevation capture look like this) --
        # shouldn't KeyError, the field is just omitted from the result,
        # same convention as "HRZones"/"runningIndex" elsewhere.
        data = [_run("2026-01-01T08:00:00")]

        result = Exercise(data).training_load()

        self.assertNotIn("total_elevation_gain_ft", result["7d"])
        self.assertNotIn("total_elevation_descent_ft", result["7d"])

    def test_gain_and_descent_density_is_total_over_total_distance(self):
        # A raw total doesn't answer "is my terrain hilly enough for the
        # race" -- the race has a fixed elevation-per-distance profile
        # (e.g. 7,000ft over 48mi), so density (ft/mile) is the comparable
        # metric. distance=5.0 (default) x 2 runs = 10mi; gain 1000ft ->
        # 100 ft/mile.
        data = [
            _run("2026-01-01T08:00:00", elevation_ascent=800, elevation_descent=750),
            _run("2026-01-05T08:00:00", elevation_ascent=200, elevation_descent=150),
        ]
        result = Exercise(data).training_load()

        self.assertEqual(result["7d"]["elevation_gain_ft_per_mile"], 100.0)
        self.assertEqual(result["7d"]["elevation_descent_ft_per_mile"], 90.0)

    def test_density_omitted_when_distance_is_zero(self):
        # Guard against a real ZeroDivisionError -- omit rather than
        # compute a false 0 or crash, same convention as
        # load_management's acute_chronic_load_ratio.
        data = [_run("2026-01-01T08:00:00", distance=0.0, elevation_ascent=500, elevation_descent=400)]

        result = Exercise(data).training_load()

        self.assertEqual(result["7d"]["total_elevation_gain_ft"], 500)
        self.assertNotIn("elevation_gain_ft_per_mile", result["7d"])
        self.assertNotIn("elevation_descent_ft_per_mile", result["7d"])


class TestLoadManagement(unittest.TestCase):
    def test_acute_chronic_ratio_is_computed(self):
        data = [
            _run("2026-01-01T08:00:00", cardio_load=50.0),
            _run("2025-12-15T08:00:00", cardio_load=50.0),
        ]
        exercise = Exercise(data)
        result = exercise.load_management(training_load=exercise.training_load())

        self.assertIn("acute_chronic_load_ratio", result)

    def test_stable_load_is_not_reported_as_increasing(self):
        # Four weekly runs of identical cardio load spread over 5 weeks: the
        # most recent week matches the mean of the prior weeks exactly, so
        # this is the textbook definition of "stable", not "increasing".
        # 4 consecutive weekly runs (7 days apart, no gap week) so
        # resample("W") produces 4 equal bins with no zero-filled gaps.
        data = [
            _run("2025-12-04T08:00:00", cardio_load=50.0),
            _run("2025-12-11T08:00:00", cardio_load=50.0),
            _run("2025-12-18T08:00:00", cardio_load=50.0),
            _run("2025-12-25T08:00:00", cardio_load=50.0),
        ]
        exercise = Exercise(data)
        result = exercise.load_management(training_load=exercise.training_load())

        self.assertEqual(result["load_trend_28d"], "stable")

    def test_decreasing_load_is_reported_as_decreasing(self):
        data = [
            _run("2025-12-04T08:00:00", cardio_load=100.0),
            _run("2025-12-11T08:00:00", cardio_load=100.0),
            _run("2025-12-18T08:00:00", cardio_load=100.0),
            _run("2025-12-25T08:00:00", cardio_load=10.0),
        ]
        exercise = Exercise(data)
        result = exercise.load_management(training_load=exercise.training_load())

        self.assertEqual(result["load_trend_28d"], "decreasing")

    def test_insufficient_data_is_reported_as_such(self):
        data = [_run("2026-01-01T08:00:00")]
        exercise = Exercise(data)
        result = exercise.load_management(training_load=exercise.training_load())

        self.assertEqual(result["load_trend_28d"], "insufficient_data")


class TestIntensityDistribution(unittest.TestCase):
    def test_zone_percentages_sum_close_to_100(self):
        data = [_run("2026-01-01T08:00:00")]
        result = Exercise(data).intensity_distribution()

        zones_7d = result["7d"]
        # Recovery=5, Zone1=10, Zone2=20, Zone3=15, Zone4=5 -> total 55
        self.assertEqual(zones_7d["zone1_pct"], round(10 / 55 * 100))
        self.assertEqual(zones_7d["zone2_pct"], round(20 / 55 * 100))
        self.assertEqual(zones_7d["zone3_pct"], round(15 / 55 * 100))
        self.assertEqual(zones_7d["zone4_pct"], round(5 / 55 * 100))

    def test_no_running_data_returns_empty_per_period(self):
        result = Exercise([_run("2026-01-01T08:00:00", sport="CYCLING")]).intensity_distribution()
        self.assertEqual(result, {"7d": {}, "28d": {}, "90d": {}})


class TestAerobicEfficiency(unittest.TestCase):
    def test_running_index_and_efficiency_factor_means(self):
        data = [
            _run("2026-01-01T08:00:00", runningIndex=50, efficiencyFactor=0.10),
            _run("2025-12-30T08:00:00", runningIndex=40, efficiencyFactor=0.06),
        ]
        result = Exercise(data).aerobic_efficiency()

        self.assertEqual(result["running_index"]["7d_mean"], 45.0)
        self.assertEqual(result["efficiency_factor"]["7d_mean"], 0.08)


class TestEnduranceSignals(unittest.TestCase):
    def test_hr_drift_and_pace_variability_means(self):
        data = [
            _run("2026-01-01T08:00:00", HRDrift=4.0, paceVariability=1.0),
            _run("2025-12-30T08:00:00", HRDrift=2.0, paceVariability=3.0),
        ]
        result = Exercise(data).endurance_signals()

        self.assertEqual(result["hr_drift"]["7d_mean"], 3.0)
        self.assertEqual(result["pace_variability"]["7d_mean"], 2.0)


class TestLongRunMetrics(unittest.TestCase):
    def test_picks_out_the_longest_run_in_the_period(self):
        data = [
            _run("2026-01-01T08:00:00", distance=10.0, duration_hr=1.5, avg_hr=150),
            _run("2025-12-30T08:00:00", distance=3.0, duration_hr=0.5, avg_hr=130),
        ]
        result = Exercise(data).long_run_metrics()

        self.assertEqual(result["7d"]["distance_m"], 10.0)
        self.assertEqual(result["7d"]["duration_hr"], 1.5)
        self.assertEqual(result["7d"]["avg_hr"], 150)

    def test_includes_gain_and_descent_of_the_longest_run(self):
        data = [
            _run(
                "2026-01-01T08:00:00",
                distance=10.0,
                elevation_ascent=1200,
                elevation_descent=1150,
            ),
            _run("2025-12-30T08:00:00", distance=3.0, elevation_ascent=100, elevation_descent=90),
        ]
        result = Exercise(data).long_run_metrics()

        self.assertEqual(result["7d"]["gain_ft"], 1200)
        self.assertEqual(result["7d"]["descent_ft"], 1150)

    def test_gain_and_descent_are_none_when_the_field_is_absent(self):
        data = [_run("2026-01-01T08:00:00", distance=10.0)]

        result = Exercise(data).long_run_metrics()

        self.assertIsNone(result["7d"]["gain_ft"])
        self.assertIsNone(result["7d"]["descent_ft"])

    def test_gain_and_descent_density_of_the_longest_run(self):
        data = [
            _run(
                "2026-01-01T08:00:00",
                distance=10.0,
                elevation_ascent=1200,
                elevation_descent=1150,
            )
        ]
        result = Exercise(data).long_run_metrics()

        self.assertEqual(result["7d"]["gain_ft_per_mile"], 120.0)
        self.assertEqual(result["7d"]["descent_ft_per_mile"], 115.0)

    def test_density_is_none_when_distance_is_zero(self):
        data = [_run("2026-01-01T08:00:00", distance=0.0, elevation_ascent=500, elevation_descent=400)]

        result = Exercise(data).long_run_metrics()

        self.assertEqual(result["7d"]["gain_ft"], 500)
        self.assertIsNone(result["7d"]["gain_ft_per_mile"])
        self.assertIsNone(result["7d"]["descent_ft_per_mile"])


class TestLongRunHistory(unittest.TestCase):
    def test_returns_top_10_by_distance_within_90_days(self):
        # 12 distinct-distance runs within 90 days -- only the top 10 by
        # distance should come back, per the athlete's own definition on
        # issue #26 (not a fixed distance/duration threshold).
        data = [_run(f"2026-01-{day:02d}T08:00:00", distance=float(day)) for day in range(1, 13)]

        history = Exercise(data).long_run_history()

        self.assertEqual(len(history), 10)
        self.assertEqual([entry["distance"] for entry in history], [12.0, 11.0, 10.0, 9.0, 8.0, 7.0, 6.0, 5.0, 4.0, 3.0])

    def test_excludes_runs_older_than_90_days(self):
        data = [
            _run("2026-01-01T08:00:00", distance=10.0),
            _run("2025-09-01T08:00:00", distance=999.0),  # >90 days before 2026-01-01
        ]

        history = Exercise(data).long_run_history()

        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["distance"], 10.0)

    def test_entry_shape_includes_gain_density_and_a_null_terrain(self):
        data = [
            _run(
                "2026-01-01T08:00:00",
                distance=10.0,
                duration_hr=2.0,
                avg_hr=150,
                elevation_ascent=1200,
                elevation_descent=1150,
            )
        ]

        history = Exercise(data).long_run_history()

        entry = history[0]
        self.assertEqual(entry["date"], "2026-01-01")
        self.assertEqual(entry["distance"], 10.0)
        self.assertEqual(entry["duration_hr"], 2.0)
        self.assertEqual(entry["gain_ft"], 1200)
        self.assertEqual(entry["descent_ft"], 1150)
        self.assertEqual(entry["gain_ft_per_mile"], 120.0)
        self.assertEqual(entry["descent_ft_per_mile"], 115.0)
        self.assertEqual(entry["avg_hr"], 150)
        self.assertEqual(entry["hr_drift_pct"], 3.0)
        self.assertIsNone(entry["terrain"])

    def test_fewer_than_10_runs_returns_all_of_them(self):
        data = [_run("2026-01-01T08:00:00"), _run("2026-01-03T08:00:00")]

        history = Exercise(data).long_run_history()

        self.assertEqual(len(history), 2)

    def test_empty_input_returns_empty_list(self):
        self.assertEqual(Exercise([]).long_run_history(), [])


class TestTrends(unittest.TestCase):
    def test_weekly_distance_trend_positive_when_recent_week_is_higher(self):
        # prev_21d_df's window is [today-28d, today-7d) = [2025-12-04, 2025-12-25)
        # for a "today" (max date) of 2026-01-01 - all 4 baseline runs below
        # fall strictly inside that window.
        data = [
            _run("2026-01-01T08:00:00", distance=14.0),  # last 7 days
            _run("2025-12-21T08:00:00", distance=7.0),  # prev 21 days (baseline)
            _run("2025-12-16T08:00:00", distance=7.0),
            _run("2025-12-11T08:00:00", distance=7.0),
            _run("2025-12-06T08:00:00", distance=7.0),
        ]
        # baseline_weekly_distance = 28 miles / 4 = 7; last_week = 14 -> (14-7)/7 = 1.0
        self.assertEqual(Exercise(data).weekly_distance_trend(), 1.0)

    def test_long_run_trend_zero_baseline_returns_none(self):
        data = [
            _run("2026-01-01T08:00:00", distance=10.0),
            # A recorded 0-distance "run" inside the prev_21d_df baseline
            # window - baseline_long_run == 0 exactly, not just "no data".
            _run("2025-12-15T08:00:00", distance=0.0),
        ]
        self.assertIsNone(Exercise(data).long_run_trend())

    def test_long_run_trend_no_baseline_data_returns_none_not_nan(self):
        # With *no* rows at all in the prev_21d_df window (as opposed to a
        # row with distance==0), max() on an empty pandas Series is NaN,
        # which the original `== 0` guard didn't catch, returning a literal
        # NaN instead of None -- not safe to round-trip through the JSON
        # this becomes for an LLM tool result. Fixed with an explicit
        # pd.isna() check alongside the == 0 check.
        data = [_run("2026-01-01T08:00:00", distance=10.0)]
        result = Exercise(data).long_run_trend()
        self.assertIsNone(result)


class TestExerciseSummary(unittest.TestCase):
    def test_summary_contains_all_expected_top_level_keys(self):
        data = [_run("2026-01-01T08:00:00")]
        result = Exercise(data).exercise_summary()

        for key in (
            "training_load",
            "load_management",
            "intensity_distribution",
            "aerobic_efficiency",
            "endurance_signals",
            "long_run_metrics",
            "long_run_history",
            "validity_metrics",
            "trend_analysis",
        ):
            self.assertIn(key, result)
        self.assertEqual(result["validity_metrics"]["7d_sample_days"], 1)


if __name__ == "__main__":
    unittest.main()
