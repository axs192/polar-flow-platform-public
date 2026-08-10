"""
Module to support the creation of the load for DynamoDB
Table
"""

import logging
from decimal import Decimal as dec

from src.app.ETL.transform import Transform
from src.app.helpers.config_loader import config_loader


class load_creator:
    def __init__(self, response: dict = None):
        self.response = response
        self.config = config_loader()

    def helper_value_handler(self, value: float):
        """
        Handles the value and returns either None or Decimal
        """
        try:
            if value is not None:
                return dec(str(value))
            else:
                return None

        except (TypeError, ValueError) as e:
            logging.error(f"Error coverting value : {e}")
            return None

    def create_load(self, **kwargs):

        try:
            logging.info("Creating summary stats for exercise data")

            date = self.response.get("start_time")  # 2026-02-22T07:50:17

            sport = self.response.get("sport")

            transform = Transform(response=self.response)

            logging.info("Creating exercise summary stats for %s on %s", sport, date)
            load = {
                "uid": str(self.config["user_id"]),
                "date": date,
                "sport": sport,
                "durationSec": self.helper_value_handler(transform.calculate_duration()),
                "distance": self.helper_value_handler(transform.calculate_distanceMiles()),
                "averageHeartRate": self.response.get("heart_rate").get("average"),
                "peakHeartRate": self.response.get("heart_rate").get("maximum"),
                "cardioLoad": self.helper_value_handler(
                    self.response.get("training_load_pro").get("cardio-load")
                ),
                "HRZones": transform.calculate_zones(),
                "load_density": self.helper_value_handler(transform.calculate_loadDensity()),
            }

            if sport == "RUNNING":
                up, down = transform.get_elevation_data()
                load.update(
                    {
                        "averagePace": dec(str(transform.calculate_meanPace())),
                        "HRDrift": dec(str(transform.calculate_HRDrift())),
                        "paceVariability": dec(str(transform.calculate_paceVariability())),
                        "runningIndex": self.response.get("running_index"),
                        "efficiencyFactor": dec(str(transform.calculate_efficiencyFactor())),
                        "elevation_ascent": up,
                        "elevation_descent": down,
                    }
                )
            return load

        except Exception as e:
            logging.error(f"Error creating exercise load: {e}")
            return None
