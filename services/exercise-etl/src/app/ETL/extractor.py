# /// extractor
# requires-python = ">=X.XX" TODO: Update this to the minimum Python version

import logging
import os
from pathlib import Path

from src.app.accesslink.accesslink import AccessLink
from src.app.helpers.config_loader import config_loader
from src.app.helpers.logging_config import setup_logging


class Extractor:
    """ """

    def __init__(self):
        try:
            self.config = config_loader()
        except Exception as e:
            logging.critical("Failed to load config: %s", {e})
            raise

        setup_logging()

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

    def get_exercises(self) -> list:
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

    def get_specifc_exercise(self, exerciseId: str) -> dict:
        """
        Get users exercise using hashed id - https://www.polar.com/accesslink-api/?python#get-exercise

        param exerciseID: Hased Exercise id.
        return: returns a JSON disctionary of the exercise information
        rtype: Dict
        """
        try:
            if exerciseId is None:
                logging.info("No Exercise ID")
                return None

            exercise_info = self.accesslink.exercises.get_exercise(
                access_token=self.config["access_token"], exerciseId=exerciseId
            )

            return exercise_info

        except Exception as e:
            logging.error(
                "Failed to get exercise information, catostrophic error: %s",
                {e},
            )
            return {}

    def get_specifc_exercise_FIT_file(self, exerciseId: str):
        """
        Get users exercise FIT file file using hashed id - https://www.polar.com/accesslink-api/?python#get-exercise

        param exerciseID: Hased Exercise id.
        return: returns a FIT file of the exercise information
        rtype: Dict
        """
        try:
            if exerciseId is None:
                logging.info("No Exercise ID")
                return None

            fit_bytes = self.accesslink.exercises.get_exercise_FIT_file(
                access_token=self.config["access_token"], exerciseId=exerciseId
            )

            if not fit_bytes:
                logging.info("No FIT payload returned for exercise: %s", {exerciseId})
                return None

            path = os.environ["FIT_FILE"]

            output_path = Path(path)
            output_path.write_bytes(fit_bytes)

            return True

        except Exception as e:
            logging.error(
                "Failed to get exercise information, catostrophic error: %s",
                {e},
            )
            raise


# End-of-file (EOF)
