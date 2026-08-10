"""Module providing a class with functions to return information from Polar Flow API."""

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from src.app.accesslink.accesslink import AccessLink
from src.app.ETL.dynamo import Health_Record
from src.app.helpers.config_loader import config_loader


@dataclass
class HealthData:
    activities: dict[str, Any] = field(default_factory=dict)
    sleep: dict[str, Any] = field(default_factory=dict)
    recharge: dict[str, Any] = field(default_factory=dict)
    heart_rate: dict[str, Any] = field(default_factory=dict)
    physical_info: dict[str, Any] = field(default_factory=dict)
    daily_activity: dict[str, Any] = field(default_factory=dict)


class Extractor:
    """
    Extractor contains two main functions:
        get_user_information - return user data from Polar Flow
        get_activites_for_date - returns daily activity data between two dates
    """

    def __init__(self):
        try:
            self.config = config_loader()
        except Exception as e:
            logging.critical("Failed to load config: %s", {e})
            raise

        if "access_token" not in self.config:
            logging.error(
                "Authorization is required. Run authorization.py"
                "first and complete the authentication process."
            )
            return

        try:
            self.accesslink = AccessLink(
                client_id=self.config["client_id"],
                client_secret=self.config["client_secret"],
            )
        except Exception as e:
            logging.critical("Failed to initialize AccessLink: %s", {e})
            raise

    def get_user_information(self):
        """Get user information and return this back"""
        user_info = self.accesslink.users.get_information(
            user_id=self.config["user_id"], access_token=self.config["access_token"]
        )
        return user_info

    def __get_dates(self, **kwargs) -> dict:

        if "to_date" in kwargs:
            try:
                to_date = kwargs["to_date"]
            except Exception as e:
                logging.warning(f"Invalid start_date format '{kwargs['to_date']}': {e}")
                to_date = datetime.now()

            if "days" in kwargs:
                from_date = to_date - timedelta(days=kwargs["days"])

            else:
                from_date = to_date - timedelta(days=4)
        else:
            to_date = datetime.now() - timedelta(days=1)

            if "days" in kwargs:
                from_date = to_date - timedelta(days=kwargs["days"])

            else:
                from_date = to_date - timedelta(days=4)

        from_date = from_date.strftime("%Y-%m-%d")
        to_date = to_date.strftime("%Y-%m-%d")

        return {"from_date": f"{from_date}", "to_date": f"{to_date}"}

    def get_activities_for_date(self, **kwargs):
        """Fetch activities between two dates from AccessLink API.

        If `to_date` argument is given, this is given as the start date to get activities
        from, otherwise utc.now is used. If `days` argument is given, from_date is calculated
        from subtracting days from `to_date`, otherwise it defaults to 4 days.
        """  # noqa: E501
        dates = self.__get_dates(**kwargs)

        from_date = dates["from_date"]
        to_date = dates["to_date"]

        try:
            activity_info = self.accesslink.activity.get_activities_between_date(
                access_token=self.config["access_token"],
                from_date=from_date,
                to_date=to_date,
            )
            return activity_info
        except Exception as e:
            logging.error(
                "Failed to get activities between %s and %s: %s",
                {from_date},
                {to_date},
                {e},
            )
            return {}

    def get_heartrate_for_date(self, **kwargs) -> dict:
        """Fetch continuous Heart Rate between two dates from AccessLink API.

        If `to_date` argument is given, this is given as the start date to get HR
        from, otherwise utc.now is used. If `days` argument is given, from_date is
        calculated from subtracting days from `to_date`, otherwise it defaults to 4 days
        """

        dates = self.__get_dates(**kwargs)

        from_date = dates["from_date"]
        to_date = dates["to_date"]

        try:
            heartrate_info = self.accesslink.heart_rate.get_heartrate_between_date(
                access_token=self.config["access_token"],
                from_date=from_date,
                to_date=to_date,
            )
            return heartrate_info
        except Exception as e:
            logging.error(
                "Failed to get heart between %s and %s: %s",
                {from_date},
                {to_date},
                {e},
            )
            return {}

    def get_sleep_for_date(self, **kwargs) -> dict:
        """Fetch sleep for a single date from AccessLink API.

        If `to_date` argument is given, this is used as when to get sleep.
        Otherwise, today is given
        """
        dates = self.__get_dates(**kwargs)

        date = dates["to_date"]

        try:
            sleep_info = self.accesslink.sleep.get_sleep_for_date(
                access_token=self.config["access_token"], date=date
            )
            return sleep_info
        except Exception as e:
            logging.error(
                "Failed to get sleep for %s: %s",
                {date},
                {e},
            )
            return {}

    def get_todays_sleep(self):

        date = datetime.now().strftime("%Y-%m-%d")
        try:
            sleep_info = self.accesslink.sleep.get_sleep_for_date(
                access_token=self.config["access_token"], date=date
            )
            return sleep_info
        except Exception as e:
            logging.error(
                "Failed to get sleep for %s: %s",
                {date},
                {e},
            )
            return {}

    def get_recharge_for_date(self, **kwargs) -> dict:
        """Fetch nightly recharge data for a single date from AccessLink API.

        If `to_date` argument is given, this is used as when to get nightly recharge.
        Otherwise, today is given
        """

        dates = self.__get_dates(**kwargs)

        date = dates["to_date"]

        try:
            recharge_info = self.accesslink.recharge.get_recharge_for_date(
                access_token=self.config["access_token"], date=date
            )
            return recharge_info
        except Exception as e:
            logging.error(
                "Failed to get nightly recharge for %s: %s",
                {date},
                {e},
            )
            return {}

    # TODO: Update this to incorporate date as an argument
    def get_todays_recharge(self):

        date = datetime.now().strftime("%Y-%m-%d")

        try:
            recharge_info = self.accesslink.recharge.get_recharge_for_date(
                access_token=self.config["access_token"], date=date
            )
            return recharge_info
        except Exception as e:
            logging.error(
                "Failed to get nightly recharge for %s: %s",
                {date},
                {e},
            )
            return {}

    # TODO: The yesterday_date part is creating an error in this, because it is not
    # always yesterday date. Therefore the date to return needs to be the latest.
    # Though I will have latest date by then ->
    # #so I can send it to this as an argument into extractor
    def get_physical_info(self, **kwargs):
        """
        Fetch Physical Info from AccessLink, if none available, gets last physcial info
        recorded in DynamoDB
        """

        try:
            if "date" in kwargs:
                try:
                    date = kwargs["date"].strftime("%Y/%m/%d")
                except Exception as e:
                    logging.warning(f"Invalid start_date format '{kwargs['date']}': {e}")
                    date = datetime.now().strftime("%Y/%m/%d")
            else:
                yesterday_date = datetime.now() - timedelta(days=2)
                date = yesterday_date.strftime("%Y/%m/%d")

            transaction = self.accesslink.physical_info.create_transaction(
                user_id=self.config["user_id"], access_token=self.config["access_token"]
            )

            if not transaction:
                logging.info("No new physical information available.")

                table_name = os.environ["TABLE_NAME"]
                health_record = Health_Record()
                table_exists = health_record.exists(table_name)
                if not table_exists:
                    print(f"\nNo Table called: {table_name}...")

                uid = self.config["user_id"]

                full_record = health_record.get_record(uid=uid, date=date)

                return full_record

            resource_urls = transaction.list_physical_infos()["physical-informations"]

            physical_info = transaction.get_physical_info(resource_urls[0])

            transaction.commit()

            return physical_info

        except Exception as e:
            logging.error(
                "Failed to get physical info: %s",
                {e},
            )
            return {}

    def get_exercises(self, **kwargs) -> list:
        """
        This is a function to return a list of all exercises completed by the user
        within the last 30 days, which have been uploaded to polar flow.

        :param kwargs: Description
        :return: returns a list of exercises within the last 30 days
        :rtype: List
        """

        try:
            exercise_info = self.accesslink.exercises.list_exercise(
                access_token=self.config["access_token"],
            )
            return exercise_info
        except Exception as e:
            logging.error(
                "Failed to get exercise information: %s",
                {e},
            )
            return []

    def extraction_decider(self):
        """
        Takes UTC.now and based on the day, determines the dates to return.
        If Monday, it returns all dates for the previous week.
        If Friday, it returns dates between Mon - Thur.
        Else, it returns the dates for the previous day.
        """

        now = datetime.now()

        if int(now.strftime("%w")) == 1:
            days = 6
            to_date = now - timedelta(days=1)  # yesterday's dates
            return to_date, days

        elif int(now.strftime("%w")) == 5:
            days = 3
            to_date = now - timedelta(days=1)  # yesterday's date
            return to_date, days
        else:
            days = 0
            to_date = now - timedelta(days=1)
            return to_date, days

    def extractor(self, **kwargs) -> HealthData:
        """
        This function conducts multiple API Calls to Polar and returns a Dict
        of sleep, recharge, heart_rate, daily_activity and physical information.

        params:
            date_1: This is the first date used, and will be latest date i.e. today
            date_2: This is the second date used, and will be the oldest date /yesterday
        """
        date_1 = kwargs["date_1"]  # today
        date_2 = kwargs["date_2"]  # today -1 day
        date_3 = kwargs["date_3"]  # the date of the last record in DynamoDB

        return HealthData(
            sleep=self.get_sleep_for_date(to_date=date_1),
            recharge=self.get_recharge_for_date(to_date=date_1),
            heart_rate=self.get_heartrate_for_date(to_date=date_2, days=0),
            daily_activity=self.get_activities_for_date(to_date=date_2, days=0),
            physical_info=self.get_physical_info(date=date_3),
        )


# End-of-file (EOF)
