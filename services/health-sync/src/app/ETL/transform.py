"""Module used to transfrom the data that has been
recieved from the extractor function"""

import logging
from datetime import datetime, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd


class Transform:
    def __init__(self, response, start_date: datetime = None, days: int = 4):
        if not response:
            logging.error("No data provided.")
            return
        self.response = response
        self.days = days
        # Need to add some logic to 1 validate it is datetime and 2 ensure that it has a value.
        self.start_date = self.process_datetime(start_date)
        self.goal = 8000

    def date_conversion(self, date_string):
        """Convert ISO datetime string to mm/dd/yy format."""
        format_code = "%Y-%m-%dT%H:%M"
        try:
            parsed_date = datetime.strptime(date_string, format_code)
            return parsed_date.strftime("%x")
        except Exception as e:
            logging.warning("Invalid date format for '%s': %s", {date_string}, {e})
            return None

    def process_datetime(self, start_date=None):
        if not start_date:
            return None

        if isinstance(start_date, datetime):
            return start_date

        if isinstance(start_date, str):
            try:
                return datetime.fromisoformat(start_date)
            except ValueError as err:
                raise TypeError("String must be a valid ISO datetime") from err

        raise TypeError("Value must be a datetime (or vlaid datetime string)")

    def extract_steps_df(self):
        """Extract the start_time and Steps from the JSON Response"""
        staging = []
        for item in self.response:
            try:
                date = self.date_conversion(item.get("start_time"))
                steps = item.get("steps")
                if date is not None and steps is not None:
                    staging.append([date, steps])
                    logging.debug("Appended date: %s, steps: %s", {date}, {steps})
                else:
                    logging.warning("Missing date or steps in item: %s", item)
            except Exception as e:
                logging.error("Error extracting steps: %s", e)
        if not staging:
            logging.error("No valid steps data extracted.")
        return pd.DataFrame(staging, columns=["date", "steps"])

    def join_response_df(self):
        """Join weekly dates with steps data."""
        steps_df = self.extract_steps_df()
        if steps_df.empty or steps_df["steps"].isnull().all():
            logging.error(
                "No steps data found after joining. Please changethe date range and try again."
            )
            raise ValueError(
                "No steps data found after joining. Please changethe date range and try again."
            )
        calendar_df = self.create_calender_df()
        try:
            result = calendar_df.set_index("date").join(steps_df.set_index("date")).sort_index()
            logging.info("Successfully joined calendar and steps data.")
            return result
        except Exception as e:
            logging.error("Error joining dataframes: %s", e)
            return pd.DataFrame()

    def create_calender_df(self):
        """
        Create a DataFrame of calendar dates.
        If start_date is provided, start from that date; otherwise, use today.
        """
        if self.start_date:
            try:
                base_date = self.start_date
            except Exception as e:
                logging.warning(f"Invalid start_date format '{self.start_date}': {e}")
                base_date = datetime.now()
        else:
            base_date = datetime.now()
        staging = []
        for x in range(self.days + 1):
            new_date = base_date - timedelta(days=x)
            staging.append(new_date.strftime("%x"))
        logging.debug(f"Generated calendar dates: {self.days + 1}")
        return pd.DataFrame(staging, columns=["date"])

    def calculate_average_hr(self):
        """
        Calculates and returns average heart rate over the last 24hour period
        """
        try:
            logging.info("Calculating Heart Rate Average")

            df = pd.DataFrame(self.response["heart_rate_samples"])

            df.drop(df[df["heart_rate"] == 0].index, inplace=True)  # Remove zero values

            df["start_time"] = df["sample_time"].shift(1)  # Create StartTime Column

            df.loc[0, "start_time"] = "00:00:00"  # Add beginning time of day

            df["start_time"] = pd.to_datetime(df["start_time"], format="%H:%M:%S")

            df["sample_time"] = pd.to_datetime(df["sample_time"], format="%H:%M:%S")

            df["duration"] = df["sample_time"] - df["start_time"]

            df["duration"] = df["duration"].dt.total_seconds()

            df["total_hr"] = df["duration"] * df["heart_rate"]

            average_hr = df["total_hr"].sum() / df["duration"].sum()

            return Decimal(str(round(average_hr, 1)))

        except Exception as e:
            logging.error("Error extracting average heart rate: %s", e)
            return {}

    def calculate_maxHR(self):
        """
        Calculates and returns max heart rate over the last 24hour period
        """
        try:
            logging.info("Calculate Max Heart for the Time Period")

            staging = []

            for x in self.response["heart_rate_samples"]:
                staging.append(x["heart_rate"])

            values = np.array(staging)

            max_value = np.max(values)

            return max_value

        except Exception as e:
            logging.error("Error extracting max heart rate: %s", e)
            return {}

    def calculate_minHR(self):
        """
        Calculates and returns min heart rate over the last 24hour period
        """
        try:
            logging.info("Calculate Max Heart for the Time Period")

            staging = []

            for x in self.response["heart_rate_samples"]:
                staging.append(x["heart_rate"])

            values = np.array(staging)

            min_value = np.min(values[np.nonzero(values)])

            return min_value

        except Exception as e:
            logging.error("Error extracting min heart rate: %s", e)
            return {}

    def calculate_minutes(self, start, end):

        start_time = datetime.strptime(start, "%H:%M:%S")
        end_time = datetime.strptime(end, "%H:%M:%S")
        delta = end_time - start_time
        sec = delta.total_seconds()
        value = round((sec / 60), 2)
        minutes = Decimal(str(value))

        return minutes

    def calculate_exercise_brackets(self):
        """
        Calculates the amount of time spent in HR zones, defined below
        Moderate = 52% to 80%
        Vigorous = >80%

        More information on HR here:
        https://www.bhf.org.uk/informationsupport/heart-matters-magazine/medical/ask-the-experts/heart-rate-exercise
        https://www.polar.com/en/guide/heart-rate-zones / Above 0.8 will be considered vigorous (Z4-5)

        Return two values, in minutes for these activties
        """

        try:
            logging.info("Calculate exercise brackets")

            max_hr = 189

            moderate_upper = max_hr * 0.80
            moderate_lower = max_hr * 0.52

            moderate_time = 0
            vigorous_time = 0
            items = self.response["heart_rate_samples"]

            for x, item in enumerate(items):
                if x > 0 and item["heart_rate"] >= moderate_lower:
                    if item["heart_rate"] >= moderate_upper:
                        # calculate minutes
                        minutes = self.calculate_minutes(
                            start=items[x - 1]["sample_time"], end=item["sample_time"]
                        )
                        vigorous_time += minutes

                    else:
                        # calculate minutes
                        minutes = self.calculate_minutes(
                            start=items[x - 1]["sample_time"], end=item["sample_time"]
                        )
                        moderate_time += minutes

            return {
                "moderate_activity": Decimal(str(round(moderate_time, 1))),
                "vigorous_activity": Decimal(str(round(vigorous_time, 1))),
            }

        except Exception as e:
            logging.error("Error calculcating exercises brackets: %s", e)

    def calculate_activity_score(self, moderate_act, vigorous_act):
        """
        Function that calculates activity score, multiplying moderate activity by 0.6 points
        and vigorous activity by 1.32 points.
        https://www.nhs.uk/live-well/exercise/physical-activity-guidelines-for-adults-aged-19-to-64/
        """
        try:
            activity_score = 0
            activity_score = +(float(moderate_act) * 0.67)
            activity_score = activity_score + (float(vigorous_act) * 1.33)

            if activity_score > 65:
                activity_score = 65

                return activity_score

            else:
                return Decimal(str(activity_score))

        except Exception as e:
            logging.error("Error calculating activity score: %s", e)

    def daily_sleep(self):
        """
        Calculate total sleep
        """
        try:
            logging.info("Calculating daily sleep")
            light_sleep = self.response["light_sleep"]
            deep_sleep = self.response["deep_sleep"]
            rem_sleep = self.response["rem_sleep"]
            unrecognized_sleep_stage = self.response["unrecognized_sleep_stage"]

            total_interruption_duration = self.response["total_interruption_duration"]

            total_sleep = (
                light_sleep + deep_sleep + rem_sleep + unrecognized_sleep_stage
            ) - total_interruption_duration

            return total_sleep

        except Exception as e:
            logging.error("Error calculating sleep score: %s", e)
            return

    def create_metrics(self) -> dict:
        """
        Provide Polar Metrics for a Polar DataFrame

        Response columns are the following:
        : Response as Dict, Total_Steps
        : Average_Steps, Best_Day
        : Most_Steps, %_Goal_Achieved
        : No._of_Steps_Left, No_Missed_Days
        """
        goal = self.goal
        df2 = self.join_response_df()
        metrics = {}
        try:
            metrics["No_Missed_Days"] = df2["steps"].isnull().sum()

            if metrics["No_Missed_Days"] >= 1 and df2["steps"].count() == 0:
                metrics["No_Data"] = 1
                logging.info("No data has been synced.")
                return metrics
            if metrics["No_Missed_Days"] >= 1:
                df2["steps"] = df2["steps"].fillna(df2["steps"].mean())
            metrics["Total_Goal"] = goal * (self.days + 1)
            metrics["Total_Steps"] = df2["steps"].sum()
            metrics["Daily_Goal"] = goal
            metrics["Average_Steps"] = df2["steps"].mean()
            metrics["Best_Day"] = df2["steps"].idxmax()
            metrics["Most_Steps"] = df2["steps"].max()
            metrics["%_Goal_Achieved"] = df2["steps"].sum() / goal
            metrics["No._of_Steps_Left"] = goal - df2["steps"].sum()
            metrics["No_Data"] = 0
            logging.info("Successfully created metrics.")
            return metrics

        except Exception as e:
            logging.error(f"Error creating metrics: {e}")
            return metrics


# End-of-file (EOF)
