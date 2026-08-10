import logging
from decimal import Decimal

import numpy as np
import pandas as pd


class Helpers:
    def __init__(self):
        pass

    def helper_decimal_to_native(self, obj):
        """To normalise values within a list or dict, to return non-dec numbers. So JSON object
        works correctly.

        Parameters
        ----------
        obj : _type_
            The item that you want to convert/search for decimal conversion

        Returns
        -------
        _type_
            normalised value / non-decimal value within list/dictionary obj
        """
        try:
            if isinstance(obj, list):
                return [self.helper_decimal_to_native(i) for i in obj]

            if isinstance(obj, dict):
                return {k: self.helper_decimal_to_native(v) for k, v in obj.items()}

            if isinstance(obj, Decimal):
                return int(obj) if obj % 1 == 0 else float(obj)

            return obj

        except (TypeError, KeyError, AttributeError) as e:
            logging.error("Error converting decimel to number: %s", {e})
            raise

    def helper_add_data_dataframe(
        self, df: pd.DataFrame, data: list, date_format: str
    ) -> pd.DataFrame:
        """_Helper function to add data to a specified dataframe_

        Parameters
        ----------
        df : pd.DataFrame
            _description_
        data : list
            _description_

        Returns
        -------
        pd.DataFrame
            _description_
        """
        try:
            for x in data:
                new_row = pd.Series(x)
                df = pd.concat([df, new_row.to_frame().T], ignore_index=True)

            df["date"] = pd.to_datetime(df["date"], format=date_format)

            df = df.sort_values("date")
            df = df.set_index("date")

            return df

        except (TypeError, KeyError) as e:
            logging.error("Error with helper_add_data_dataframe: %s", {e})
            raise

    def helper_trend_analysis(self, df_28: pd.DataFrame, df_7: pd.DataFrame, column: str) -> dict:
        """_summary_

        Parameters
        ----------
        df_28 : pd.DataFrame
            _description_
        df_7 : pd.DataFrame
            _description_
        column : str
            _description_

        Returns
        -------
        dict
            _description_
        """

        y = pd.to_numeric(df_28[column], errors="coerce").dropna()
        y7 = pd.to_numeric(df_7[column], errors="coerce").dropna()

        if len(y) >= 3:
            x = np.arange(len(y))
            trend = np.polyfit(x, y, 1)[0]
            trend_per_week = trend * 7
        else:
            trend = np.nan
            trend_per_week = np.nan

        min_7d = y7.min()

        lowest_3d = y7.rolling(3, min_periods=3).mean().min()

        return {
            "trend": trend,
            "trend_per_week": trend_per_week,
            "min_7d": min_7d,
            "lowest_3d": lowest_3d,
        }
