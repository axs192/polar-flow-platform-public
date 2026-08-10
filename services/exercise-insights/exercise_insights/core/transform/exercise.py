"""_summary_

Returns
-------
_type_
    _description_
"""

import logging

import pandas as pd

from .helpers import Helpers


class Exercise:
    """_summary_"""

    def __init__(self, response: list):
        # No early return on empty response: every method below already has
        # its own `if self.running_df.empty: return {...}` guard, so this
        # class was clearly designed to degrade gracefully on no data -- but
        # an early return here skipped create_running_dataframes() entirely,
        # leaving those attributes unset and every guard's own attribute
        # access raising AttributeError before it could run. Empty input
        # flows through create_running_dataframes() like any other input and
        # produces correctly-shaped empty DataFrames (verified directly:
        # pandas' NaT-based comparisons on an empty index short-circuit to
        # empty results, not an exception).
        if not response:
            logging.error("No data provided.")
        self.response = response or []
        self.running_df, self.df_7d, self.df_28d, self.df_90, self.prev_21d_df = (
            self.create_running_dataframes()
        )

    def create_running_dataframes(self):
        try:
            # Normalise the values, so no decimal
            normalised_data = Helpers().helper_decimal_to_native(self.response)

            # Place into Dataframe
            column_names = [
                "date",
                "distance",
                "durationSec",
                "cardioLoad",
                "sport",
                "averageHeartRate",
                "HRDrift",
                "HRZones",
                "paceVariability",
                "efficiencyFactor",
            ]

            df = pd.DataFrame(columns=column_names)

            # filter by running

            date_format = "%Y-%m-%dT%H:%M:%S"  # "2026-02-01T06:35:07"

            full_df = Helpers().helper_add_data_dataframe(
                df=df, data=normalised_data, date_format=date_format
            )

            running_df = full_df[full_df["sport"] == "RUNNING"].copy()

            today = running_df.index.max()

            start_7d = today - pd.Timedelta(days=7)
            df_7d = running_df[(running_df.index >= start_7d) & (running_df.index <= today)]

            # 28-day period
            start_28d = today - pd.Timedelta(days=28)
            df_28d = running_df[(running_df.index >= start_28d) & (running_df.index <= today)]

            # 90-day period
            start_90d = today - pd.Timedelta(days=90)
            df_90d = running_df[(running_df.index >= start_90d) & (running_df.index <= today)]

            prev_21_df = running_df[(running_df.index < start_7d) & (running_df.index >= start_28d)]

            return running_df, df_7d, df_28d, df_90d, prev_21_df

        except Exception as e:
            # Must re-raise: __init__ unpacks this into 5 attributes, so a
            # bare log-and-return-None here breaks with a confusing
            # "cannot unpack non-iterable NoneType object" TypeError instead
            # of the real, already-logged error (confirmed live with a
            # malformed date -- the ValueError logged above never reached
            # the caller, only the unrelated TypeError did).
            logging.error("Error creating running dataframes: %s", {e})
            raise

    def training_load(self):
        """Calculate training load metrics for 7d, 28d, and 90d periods.

        Returns
        -------
        dict
            Training load statistics with keys '7d', '28d', '90d' containing:
            - total_cardio_load: sum of cardio load
            - total_distance_km: sum of distance
            - total_duration_hr: total duration in hours
            - runs: number of runs
            - longest_run_km: longest single run
            - avg_weekly_distance_km: (for 28d, 90d)
            - avg_weekly_duration_hr: (for 28d, 90d)
            - avg_weekly_cardio_load: (for 28d, 90d)
            - runs_per_week: (for 28d, 90d)
        """
        try:
            if self.running_df.empty:
                return {"7d": {}, "28d": {}, "90d": {}}

            result = {}

            # 7-day period
            result["7d"] = self._calculate_training_load_period(self.df_7d)

            # 28-day period
            result["28d"] = self._calculate_training_load_period(self.df_28d, weekly=True, days=28)

            # 90-day period
            result["90d"] = self._calculate_training_load_period(self.df_90, weekly=True, days=90)

            return result

        except Exception as e:
            logging.error("Error calculating training load: %s", e)
            raise

    def _calculate_training_load_period(self, df, weekly=False, days=None):
        """Helper to calculate training load for a specific period."""
        result = {}

        if df.empty:
            return result

        if not (weekly):
            result["total_cardio_load"] = df["cardioLoad"].sum()
            result["total_distance_miles"] = df["distance"].sum()
            result["total_duration_hr"] = df["durationSec"].sum() / 3600
            result["runs"] = len(df)
            result["longest_run_miles"] = df["distance"].max()
            self._add_elevation_totals(result, df)
            return result

        if weekly and days:
            weeks = days / 7
            result["avg_weekly_distance_miles"] = round(df["distance"].sum() / weeks, 1)
            result["avg_weekly_duration_hr"] = round((df["durationSec"].sum() / 3600) / weeks, 1)
            result["avg_weekly_cardio_load"] = round(df["cardioLoad"].sum() / weeks, 1)
            result["runs_per_week"] = round(len(df) / weeks, 1)
            result["longest_run_miles"] = df["distance"].max()
            self._add_elevation_totals(result, df)

        return result

    def _add_elevation_totals(self, result: dict, df) -> None:
        """Add elevation totals and per-mile density to result, in place.

        Cumulative totals (not weekly averages, even in the 28d/90d "weekly"
        branch) -- vert accumulation toward a fixed goal (e.g. 7,000ft) is a
        total, not a rate. Already in feet: exercise-etl's
        Transform.get_elevation_data() converts metres->feet before storing
        elevation_ascent/elevation_descent, so no unit conversion happens
        here. Columns may be entirely absent (records predating this field,
        or a period with none of the underlying .fit-derived data) --
        guarded the same way "HRZones"/"runningIndex" already are elsewhere
        in this class, rather than assuming the column exists.

        Also adds *_ft_per_mile density -- a raw cumulative total doesn't
        answer the question that actually matters for race prep: the race
        itself has a fixed elevation-per-distance profile (e.g. 7,000ft over
        48mi =~ 146 ft/mile), so what's actionable is whether training gain
        density is approaching that ratio, not the total in isolation.
        Omitted (not computed as a false 0) when total_distance_miles isn't
        a positive number -- same "omit rather than divide by zero"
        convention as load_management's acute_chronic_load_ratio.
        """
        distance_miles = df["distance"].sum()

        if "elevation_ascent" in df.columns:
            gain = df["elevation_ascent"].sum()
            result["total_elevation_gain_ft"] = gain
            if distance_miles > 0:
                result["elevation_gain_ft_per_mile"] = round(gain / distance_miles, 1)
        if "elevation_descent" in df.columns:
            descent = df["elevation_descent"].sum()
            result["total_elevation_descent_ft"] = descent
            if distance_miles > 0:
                result["elevation_descent_ft_per_mile"] = round(descent / distance_miles, 1)

    def load_management(self, training_load: dict):
        """Calculate load management metrics including acute/chronic load ratio and trends.

        Returns
        -------
        dict
            Load management metrics containing:
            - acute_chronic_load_ratio: ratio of 7d to 28d average load
            - load_trend_28d: trend direction ("increasing", "stable", "decreasing")
            - load_trend_90d: trend direction ("increasing", "stable", "decreasing")
        """
        try:
            # Acute load (7d average)
            load_7d = training_load.get("7d", {}).get("total_cardio_load", 0)
            days_7d = training_load.get("7d", {}).get("runs", 0)
            acute_load = load_7d / max(days_7d, 1) if days_7d > 0 else 0

            # Chronic load (28d average)
            load_28d = training_load.get("28d", {}).get("avg_weekly_cardio_load", 0)
            days_28d = training_load.get("28d", {}).get("runs_per_week", 0)
            chronic_load = load_28d / max(days_28d, 1) if days_28d > 0 else 0

            result = {}
            # None (not 0/0 -> ZeroDivisionError) when there's no 28d baseline
            # to compare against -- confirmed live: no-data input reaches this
            # with chronic_load == 0. Matches weekly_distance_trend/
            # long_run_trend's existing "no baseline -> None" convention.
            result["acute_chronic_load_ratio"] = (
                round(acute_load / chronic_load, 2) if chronic_load > 0 else None
            )

            # Calculate trends using trend analysis
            if not self.running_df.empty:
                # 28-day trend
                twenty_trend = self._calculate_load_trend(self.df_28d)
                result["load_trend_28d"] = twenty_trend

                # 90-day trend
                ninety_trend = self._calculate_load_trend(self.df_90)
                result["load_trend_90d"] = ninety_trend

            return result

        except Exception as e:
            logging.error("Error calculating load management: %s", e)
            raise

    def _calculate_load_trend(self, df):
        """Determine load trend based on data."""
        if df.empty or len(df) < 3:
            return "insufficient_data"

        # Group by week and sum cardio loads
        weekly_sums = df.resample("W")["cardioLoad"].sum()

        if len(weekly_sums) < 2:
            return "stable"

        # Simple trend: compare last week to mean of previous weeks
        last_week = weekly_sums.iloc[-1]
        prev_mean = weekly_sums.iloc[:-1].mean()

        change_pct = (last_week - prev_mean) / prev_mean

        if change_pct > 0.1:
            return "increasing"
        elif change_pct < -0.10:
            return "decreasing"
        else:
            return "stable"

    def intensity_distribution(self):
        """Calculate intensity distribution across HR zones for 7d, 28d, and 90d.

        Returns
        -------
        dict
            Intensity distribution with keys '7d', '28d', '90d' containing:
            - zone1_pct: percentage of time in Zone 1
            - zone2_pct: percentage of time in Zone 2
            - zone3_pct: percentage of time in Zone 3
            - zone4_pct: percentage of time in Zone 4
        """
        try:
            if self.running_df.empty:
                return {"7d": {}, "28d": {}, "90d": {}}

            result = {}

            # 7-day period
            result["7d"] = self._calculate_zone_distribution(self.df_7d)

            # 28-day period
            result["28d"] = self._calculate_zone_distribution(self.df_28d)

            # 90-day period
            result["90d"] = self._calculate_zone_distribution(self.df_90)

            return result

        except Exception as e:
            logging.error("Error calculating intensity distribution: %s", e)
            raise

    def _calculate_zone_distribution(self, df):
        """Helper to calculate HR zone distribution for a period."""
        result = {}

        if df.empty or "HRZones" not in df.columns:
            return result

        # Aggregate all zone times
        total_zone1 = 0
        total_zone2 = 0
        total_zone3 = 0
        total_zone4 = 0
        total_recovery = 0

        for hr_zones in df["HRZones"]:
            if isinstance(hr_zones, dict):
                total_zone1 += hr_zones.get("Zone 1", 0)
                total_zone2 += hr_zones.get("Zone 2", 0)
                total_zone3 += hr_zones.get("Zone 3", 0)
                total_zone4 += hr_zones.get("Zone 4", 0)
                total_recovery += hr_zones.get("Recovery", 0)

        total_time = total_zone1 + total_zone2 + total_zone3 + total_zone4 + total_recovery

        if total_time > 0:
            result["zone1_pct"] = round((total_zone1 / total_time) * 100)
            result["zone2_pct"] = round((total_zone2 / total_time) * 100)
            result["zone3_pct"] = round((total_zone3 / total_time) * 100)
            result["zone4_pct"] = round((total_zone4 / total_time) * 100)

        return result

    def aerobic_efficiency(self):
        """Calculate aerobic efficiency metrics including running index and efficiency factor.

        Returns
        -------
        dict
            Aerobic efficiency metrics containing:
            - running_index: dict with 7d_mean, 28d_baseline, 90d_baseline, trend_28d
            - efficiency_factor: dict with 7d_mean, 28d_baseline, trend_28d
        """
        try:
            if self.running_df.empty:
                return {"running_index": {}, "efficiency_factor": {}}

            result = {}

            # Running Index calculations
            running_idx_result = {}

            # 7d mean
            if not self.df_7d.empty and "runningIndex" in self.df_7d.columns:
                running_idx_result["7d_mean"] = round(self.df_7d["runningIndex"].dropna().mean(), 1)

            # 28d baseline
            if not self.df_28d.empty and "runningIndex" in self.df_28d.columns:
                running_idx_result["28d_baseline"] = round(
                    self.df_28d["runningIndex"].dropna().mean(), 1
                )

            # 90d baseline
            if not self.df_90.empty and "runningIndex" in self.df_90.columns:
                running_idx_result["90d_baseline"] = round(
                    self.df_90["runningIndex"].dropna().mean(), 1
                )

                # Calculate trend
                if "28d_baseline" in running_idx_result and "90d_baseline" in running_idx_result:
                    trend = running_idx_result["28d_baseline"] - running_idx_result["90d_baseline"]
                    running_idx_result["trend_28d"] = round(trend, 1)

            result["running_index"] = running_idx_result

            # Efficiency Factor calculations
            ef_result = {}

            # 7d mean
            if not self.df_7d.empty and "efficiencyFactor" in self.df_7d.columns:
                ef_result["7d_mean"] = round(self.df_7d["efficiencyFactor"].dropna().mean(), 3)

            # 28d baseline
            if not self.df_28d.empty and "efficiencyFactor" in self.df_28d.columns:
                ef_result["28d_baseline"] = round(
                    self.df_28d["efficiencyFactor"].dropna().mean(), 3
                )

            # Calculate trend
            if "7d_mean" in ef_result and "28d_baseline" in ef_result:
                trend = ef_result["7d_mean"] - ef_result["28d_baseline"]
                ef_result["trend_28d"] = round(trend, 3)

            result["efficiency_factor"] = ef_result

            return result

        except Exception as e:
            logging.error("Error calculating aerobic efficiency: %s", e)
            raise

    def endurance_signals(self):
        """Calculate endurance signal metrics including HR drift and pace variability.

        Returns
        -------
        dict
            Endurance signals containing:
            - hr_drift: dict with 7d_mean, 28d_mean, 90d_mean
            - pace_variability: dict with 7d_mean, 28d_mean, 90d_mean
        """
        try:
            if self.running_df.empty:
                return {"hr_drift": {}, "pace_variability": {}}

            result = {}

            columns = {"hr_drift": "HRDrift", "pace_variability": "paceVariability"}

            data_frames = {"7d_mean": self.df_7d, "28d_mean": self.df_28d, "90d_mean": self.df_90}

            for metric, column_name in columns.items():
                column_result = {}
                for k, v in data_frames.items():
                    if not v.empty and column_name in v.columns:
                        column_result[k] = round(v[column_name].dropna().mean(), 1)
                result[metric] = column_result

            return result

        except Exception as e:
            logging.error("Error calculating endurance signals: %s", e)
            raise

    def long_run_metrics(self):
        """Calculate metrics for the longest runs in 7d, 28d, and 90d periods.

        Returns
        -------
        dict
            Long run metrics with keys '7d', '28d', '90d' containing:
            - distance_km: distance of longest run
            - duration_hr: duration in hours
            - avg_hr: average heart rate
            - hr_drift: HR drift value
            - zone2_pct: percentage of time in Zone 2
            - zone3_pct: percentage of time in Zone 3
        """
        try:
            if self.running_df.empty:
                return {"7d": {}, "28d": {}, "90d": {}}

            result = {}

            # 7-day period
            result["7d"] = self._get_longest_run_metrics(self.df_7d)

            # 28-day period
            result["28d"] = self._get_longest_run_metrics(self.df_28d)

            # 90-day period
            result["90d"] = self._get_longest_run_metrics(self.df_90)

            return result

        except Exception as e:
            logging.error("Error calculating long run metrics: %s", e)
            raise

    def _get_longest_run_metrics(self, df):
        """Helper to extract metrics from the longest run in a period."""
        result = {}

        if df.empty or "distance" not in df.columns:
            return result

        # Find the longest run
        longest_run = df.loc[df["distance"].idxmax()]

        result["distance_m"] = (
            round(longest_run["distance"], 1) if pd.notna(longest_run["distance"]) else None
        )
        result["duration_hr"] = (
            round(longest_run["durationSec"] / 3600, 1)
            if pd.notna(longest_run["durationSec"])
            else None
        )
        result["avg_hr"] = (
            int(longest_run["averageHeartRate"])
            if pd.notna(longest_run["averageHeartRate"])
            else None
        )
        result["hr_drift"] = (
            round(longest_run["HRDrift"], 1) if pd.notna(longest_run.get("HRDrift")) else None
        )
        result["gain_ft"] = (
            int(longest_run["elevation_ascent"])
            if pd.notna(longest_run.get("elevation_ascent"))
            else None
        )
        result["descent_ft"] = (
            int(longest_run["elevation_descent"])
            if pd.notna(longest_run.get("elevation_descent"))
            else None
        )
        # Density (ft/mile), not just a total -- the race itself has a fixed
        # elevation-per-distance profile (e.g. 7,000ft over 48mi), so this is
        # the metric that's actually comparable against it. Only computed
        # when both the gain/descent and a positive distance are known.
        distance = longest_run.get("distance")
        has_distance = pd.notna(distance) and distance > 0
        result["gain_ft_per_mile"] = (
            round(result["gain_ft"] / distance, 1)
            if result["gain_ft"] is not None and has_distance
            else None
        )
        result["descent_ft_per_mile"] = (
            round(result["descent_ft"] / distance, 1)
            if result["descent_ft"] is not None and has_distance
            else None
        )

        # Calculate zone percentages
        if "HRZones" in longest_run and isinstance(longest_run["HRZones"], dict):
            hr_zones = longest_run["HRZones"]
            total_time = sum(hr_zones.values())

            if total_time > 0:
                result["zone2_pct"] = round((hr_zones.get("Zone 2", 0) / total_time) * 100)
                result["zone3_pct"] = round((hr_zones.get("Zone 3", 0) / total_time) * 100)

        return result

    def long_run_history(self, limit: int = 10) -> list:
        """The last `limit` long runs (by distance) within the trailing 90 days.

        Returns a real array, not a per-window summary -- the one
        deliberate exception to this class otherwise keeping everything
        aggregated (per the athlete's own instruction on issue #26): a
        single aggregate HR-drift number can't distinguish "improving at
        3.5h" from "not," which needs a real per-run trend. "Long run" =
        the top `limit` runs by distance within `self.df_90` -- the
        athlete's own definition (given directly on the issue), not a
        fixed distance/duration threshold.

        Each entry: date, distance, duration_hr, gain_ft/descent_ft
        (totals) and gain_ft_per_mile/descent_ft_per_mile (density -- see
        `_add_elevation_totals`'s docstring for why density matters more
        than the raw total for race-readiness comparisons), avg_hr,
        hr_drift_pct, avg_pace, and terrain (always None today -- no data
        source yet, tracked separately in issue #31).
        """
        try:
            if self.df_90.empty:
                return []

            # sort_values, not nlargest: "distance" comes through as object
            # dtype (helper_add_data_dataframe builds the frame from
            # per-row pd.Series, not a fully-typed DataFrame), which
            # nlargest rejects outright ("cannot use method 'nlargest' with
            # this dtype") even though it holds only numeric values --
            # confirmed live against a real moto-backed round trip.
            # sort_values has no such restriction.
            top_runs = self.df_90.sort_values("distance", ascending=False, na_position="last").head(
                limit
            )

            history = []
            for run_date, row in top_runs.iterrows():
                distance = row.get("distance")
                gain = row.get("elevation_ascent")
                descent = row.get("elevation_descent")
                has_distance = pd.notna(distance) and distance > 0

                history.append(
                    {
                        "date": run_date.strftime("%Y-%m-%d"),
                        "distance": round(distance, 1) if pd.notna(distance) else None,
                        "duration_hr": (
                            round(row["durationSec"] / 3600, 1)
                            if pd.notna(row.get("durationSec"))
                            else None
                        ),
                        "gain_ft": int(gain) if pd.notna(gain) else None,
                        "descent_ft": int(descent) if pd.notna(descent) else None,
                        "gain_ft_per_mile": (
                            round(gain / distance, 1) if pd.notna(gain) and has_distance else None
                        ),
                        "descent_ft_per_mile": (
                            round(descent / distance, 1)
                            if pd.notna(descent) and has_distance
                            else None
                        ),
                        "avg_hr": (
                            int(row["averageHeartRate"])
                            if pd.notna(row.get("averageHeartRate"))
                            else None
                        ),
                        "hr_drift_pct": (
                            round(row["HRDrift"], 1) if pd.notna(row.get("HRDrift")) else None
                        ),
                        "avg_pace": (
                            row.get("averagePace") if pd.notna(row.get("averagePace")) else None
                        ),
                        "terrain": None,
                    }
                )

            return history

        except Exception as e:
            logging.error("Error calculating long run history: %s", e)
            raise

    def weekly_distance_trend(self) -> float:

        try:
            last_week_distance = self.df_7d["distance"].sum()
            baseline_weekly_distance = self.prev_21d_df["distance"].sum() / 4

            if baseline_weekly_distance == 0:
                return None

            return (last_week_distance - baseline_weekly_distance) / baseline_weekly_distance

        except Exception as e:
            logging.error("Error calculating weekly distance: %s", {e})

    def long_run_trend(self) -> float:
        try:
            recent_long_run = self.df_7d["distance"].max()
            baseline_long_run = self.prev_21d_df["distance"].max()

            # pd.isna, not just == 0: .max() on an empty/all-NaN period
            # returns NaN, not 0 (unlike weekly_distance_trend's .sum(),
            # which is 0 for empty data) -- confirmed live: no-data input
            # reached the division below and returned a literal NaN instead
            # of None, which isn't safe to round-trip through the JSON this
            # eventually becomes for the LLM tool result.
            if pd.isna(baseline_long_run) or baseline_long_run == 0:
                return None

            return (recent_long_run - baseline_long_run) / baseline_long_run

        except Exception as e:
            logging.error("Error calculating long runtrend: %s", {e})

    def exercise_summary(self):

        try:
            training_load = self.training_load()

            exercise_metrics = {
                "training_load": training_load,
                "load_management": self.load_management(training_load=training_load),
                "intensity_distribution": self.intensity_distribution(),
                "aerobic_efficiency": self.aerobic_efficiency(),
                "endurance_signals": self.endurance_signals(),
                "long_run_metrics": self.long_run_metrics(),
                "long_run_history": self.long_run_history(),
                "validity_metrics": {
                    "90d_sample_days": len(self.df_90),
                    "28d_sample_days": len(self.df_28d),
                    "7d_sample_days": len(self.df_7d),
                },
                "trend_analysis": {
                    "weekly_distance_trend": self.weekly_distance_trend(),
                    "long_run_trend": self.long_run_trend(),
                },
            }

            # Return Dict
            return exercise_metrics

        except Exception as e:
            logging.error(
                "Health summary was unable to be returned: %s,Function: def_health_summary()",
                {e},
            )
            raise

        return
