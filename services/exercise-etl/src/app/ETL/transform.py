"""
Module: To Transform the extract data from PolarAPI
"""

import logging
import os
from decimal import Decimal as dec

import isodate
import numpy as np
import pandas as pd

from src.app.helpers.fit_file_helper import load_fit_session_dataframe


class Transform:
    """
    The Transform Class to store and group functions that carry out transformation
    """

    def __init__(self, response: dict):
        if not response:
            logging.error("No data provided.")
            return
        self.response = response

    def helper_timeConvert(self, ISOTime: str) -> int:
        """
        Helper function to covert ISOTime to Seconds

        params ISOTime:  Time to convert
        return: Duration in seconds
        rtype: Int
        """
        try:
            dur = isodate.parse_duration(ISOTime)

            seconds = dur.total_seconds()

            return seconds

        except (TypeError, ValueError) as e:
            logging.error(
                "Failed to convert ISO Time: %s",
                {e},
            )
            raise

    def helper_extractSample(self, sample_key: int) -> dict:
        """
        Helper function to return sample type from key

        params: SampleKey: the key of the sample you want.
        return: a JSON Dict of the sample
        rtype: Dict
        """
        for sample in self.response.get("samples"):
            if sample.get("sample_type") == sample_key:
                return sample

        return None

    def helper_drift(self, sample: dict) -> float:
        """
        Helper function to return drift

        params: Sample: the sample you want to calculate drift on.
        return: Drift rounded to 2 decimal places
        rtype: float
        """

        sample_arr = np.fromstring(sample.get("data"), sep=",")

        df = pd.DataFrame(sample_arr, columns=["value"])

        df = df[df.index >= 600]

        midpoint = int(len(df) / 2)

        first = df["value"].iloc[:midpoint].mean()
        second = df["value"].iloc[midpoint:].mean()

        drift = round(((second - first) / first) * 100, 2)

        return drift

    def calculate_duration(self) -> int:
        """
        Conversts ISO8601 aka PT2H44M into seconds
        """
        try:
            original_dur = self.response.get("duration")
            seconds = self.helper_timeConvert(original_dur)

            return seconds

        except (KeyError, TypeError, ValueError) as e:
            logging.error(
                "Failed to get element from JSON: %s",
                {e},
            )
            return None

    def calculate_zones(self) -> dict:
        """
        Returns {"Z1": xx} format from the Polar JSON return, converting
        time and numberic zones
        """
        sample = self.response.get("heart_rate_zones")

        zones = {}

        for items in sample:
            if items.get("index") == 0:
                zones.update({"Recovery": dec(str(self.helper_timeConvert(items.get("in_zone"))))})
            else:
                zones.update(
                    {
                        "Zone " + str(items.get("index")): (
                            dec(str(self.helper_timeConvert(items.get("in_zone"))))
                        )
                    }
                )

        return zones

    def calculate_HRDrift(self) -> float:
        """
        Calculates HR Drift for the run

        Only calculate when duration is over 60 mins
        (HR second half - HR first half) / HR first half

        <5% drift = strong aerobic base
        7% drift = endurance weakness
        """

        try:
            heart_sample = self.helper_extractSample(sample_key=0)

            if heart_sample is None:
                logging.info("No sample data available for Sample Key 0: Heart Rates")
                return None

            drift = self.helper_drift(sample=heart_sample)

            return drift

        except (KeyError, TypeError, ValueError) as e:
            logging.error(
                "Failed to calculate drift: %s",
                {e},
            )
            return None

    def calculate_efficiencyFactor(self) -> float:
        """
        Calculates Speed (m/s) (i.e. average speed) / Avg HR
        """
        try:
            average_hr = self.response.get("heart_rate").get("average")

            average_speed = self.calculate_meanPace()

            if average_speed is None:
                return None

            eff_factor = round(average_speed / average_hr, 5)

            return eff_factor

        except (KeyError, TypeError, ValueError) as e:
            logging.error(
                "Failed to calculate efficiencyFactor: %s",
                {e},
            )
            return None

    def calculate_loadDensity(self) -> float:
        """
        Divides the cardio load, by the duration of the session
        """

        try:
            cardio_load = self.response.get("training_load_pro").get("cardio-load")

            duration = self.calculate_duration()

            load_dens = round((cardio_load / duration) * 100, 2)

            return load_dens

        except (KeyError, TypeError, ValueError) as e:
            logging.error(
                "Failed to calculate loadDensity: %s",
                {e},
            )
            return None

    def calculate_paceVariability(self) -> float:
        """
        Calculates the pace variability for the run.

        variability_ratio = pace_std_dev / mean_speed

        """
        try:
            pace_sample = self.helper_extractSample(sample_key=1)

            if pace_sample is None:
                logging.info("No sample data available for Sample Key 1: Pace Sample")
                return None

            drift = self.helper_drift(sample=pace_sample)

            if np.isnan(drift):
                return None

            return drift

        except (KeyError, TypeError, ValueError) as e:
            logging.error(
                "Failed to calculate drift: %s",
                {e},
            )
            return None

    def calculate_meanPace(self) -> float:
        """
        Calculate mean Pace for the Run
        """
        try:
            duration_sec = self.calculate_duration()

            distance_m = self.response.get("distance")

            if distance_m is not None:
                pace_min = round((duration_sec / ((distance_m / 1000) * 0.621371)) / 60, 2)

                return pace_min

            else:
                return None

        except (KeyError, TypeError, ValueError) as e:
            logging.error(
                "Failed to calculate mean pace: %s",
                {e},
            )
            return None

    def calculate_distanceMiles(self) -> float:
        """ """
        try:
            distance_m = self.response.get("distance")

            if distance_m is not None:
                distance_miles = round(((distance_m / 1000) * 0.621371), 1)
                return distance_miles

            else:
                logging.info("No Distance within Exercise Information")
                return None

        except (KeyError, TypeError, ValueError) as e:
            logging.error(
                "Failed to calculate distnace miles: %s",
                {e},
            )
            return None

    def get_elevation_data(self) -> int:
        """Extracts the elevation gain from the .fit file. The fit file is required to
        be loaded prior to this function running.

        Returns
        -------
        Int:
            Two Integers, the first is elevation gain, the second is descent
        """

        try:
            conversion_rate = 3.28084  # metres to feet

            file_path = os.environ["FIT_FILE"]

            session_information = load_fit_session_dataframe(filename=file_path)

            elev_gain = int(round(session_information.get("total_ascent") * conversion_rate))

            elev_desc = int(round(session_information.get("total_descent") * conversion_rate))

            return elev_gain, elev_desc

        except Exception as e:
            logging.error("Failed to get elevation information: %s", {e})
            raise
