"""_summary_

Returns
-------
_type_
    _description_
"""

import json
import logging

import pandas as pd

from .helpers import Helpers


class Health:
    """_summary_"""

    def __init__(self, response: list):
        if not response:
            logging.error("No data provided.")
            return
        self.response = response

    def helper_health_metrics(self, df: pd.DataFrame, column: str) -> dict:
        """
            7d_mean
            28d_baseline
            90d_baseline
            trend_28d
            z_score_7d_vs_28d
            std_dev_28d

        Guardrails:
            - Returns None if dataframe has fewer than 10 rows
            - Returns None if column is not available in dataframe
        """
        try:
            # Guardrail: Check minimum data availability
            if len(df) < 10:
                return None

            # Guardrail: Check if column exists
            if column not in df.columns:
                return None

            latest = df.index.max()

            df_7 = df[df.index >= latest - pd.Timedelta(days=7)]
            df_28 = df[df.index >= latest - pd.Timedelta(days=28)]
            df_90 = df[df.index >= latest - pd.Timedelta(days=90)]

            averages = {
                "mean_7d": df_7[column].mean(),
                "baseline_28d": df_28[column].mean(),
                "std_dev_28d": df_28[column].std(),
                "baseline_90d": df_90[column].mean(),
            }

            z_score = (
                (averages["mean_7d"] - averages["baseline_28d"]) / averages["std_dev_28d"]
                if averages["std_dev_28d"]
                else 0
            )

            trend_analysis = Helpers().helper_trend_analysis(df_28=df_28, df_7=df_7, column=column)

            data = {
                "mean_7d": averages["mean_7d"],
                "baseline_28d": averages["baseline_28d"],
                "baseline_90d": averages["baseline_90d"],
                "std_dev_28d": averages["std_dev_28d"],
                "delta_7d_vs_28d": averages["mean_7d"] - averages["baseline_28d"],
                "lowest_7d": trend_analysis["min_7d"],
                "lowest_3d": trend_analysis["lowest_3d"],
                "trend_28d_per_day": trend_analysis["trend"],
                "trend_28d_per_week": trend_analysis["trend_per_week"],
                "sample_size": len(df_90),
                "expected_days": 90,
                "completeness_ratio": round((len(df_90) / 90), 3),
                "z_score_7d_vs_28d": z_score,
            }

            # clean_data = json.loads(json.dumps(data, default=float))

            return json.loads(json.dumps(data, default=float))

        except (TypeError, KeyError) as e:
            logging.error(
                "Unable to create health metrics: %s, Function: def_helper_health_metrics()",
                {e},
            )
            raise

    def helper_exercise_metrics(self, duration: int):
        return

    def health_summary(self) -> dict:
        """Generates health summary JSON that can be used in the AI Prompt for summary metrics.

        Returns
        -------
        dict
            Returns the JSON dict for the key metrics (HRV, Total Sleep etc.)
        """
        try:
            # Normalise the values, so no decimal
            normalised_data = Helpers().helper_decimal_to_native(self.response)

            # Place into Dataframe
            column_names = [
                "activity_score",
                "hrv",
                "maximum-heart-rate",
                "average_daily_hr",
                "dhrps",
                "total_sleep",
                "steps",
                "date",
            ]

            df = pd.DataFrame(columns=column_names)

            date_format = "%Y/%m/%d"

            full_df = Helpers().helper_add_data_dataframe(
                df=df, data=normalised_data, date_format=date_format
            )
            health_metrics = {}

            metrics = [
                "hrv",
                "total_sleep",
                "steps",
                "dhrps",
                "ans_charge",
                "activity_score",
                "average_daily_hr",
            ]

            for metric in metrics:
                health_metrics[metric] = self.helper_health_metrics(df=full_df, column=metric)
            # Return Dict
            return health_metrics

        except Exception as e:
            logging.error(
                "Health summary was unable to be returned: %s,Function: def_health_summary()",
                {e},
            )
            raise
