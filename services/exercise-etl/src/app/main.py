"""
Main module that is run for application.
"""

import json
import logging
import os

from src.app.ETL.extractor import Extractor
from src.app.ETL.load import loader
from src.app.ETL.load_creator import load_creator
from src.app.helpers.logging_config import setup_logging


def run_app(exerciseId: str):
    """
    Docstring for run_app

    :param exerciseID: this is the exerciseID you want to upload to DynamoDB
    """
    try:
        logging.info("Successfully intitited logging.")
    except Exception as e:
        return {"message": f"logging error {e}"}

    try:
        user_data = Extractor().get_specifc_exercise(exerciseId=exerciseId)
        Extractor().get_specifc_exercise_FIT_file(exerciseId=exerciseId)  # Load .fit file
    except Exception as e:
        logging.error("Error getting information from PolarAPI: %s", e)
        raise

    try:
        load = load_creator(response=user_data).create_load()
    except Exception as e:
        logging.error("Error creating load / transforming extract data: %s", e)
        raise

    try:
        table_name = os.environ["TABLE_NAME"]
        upload = loader()
        upload.exists(table_name=table_name)
        upload.add_record(load=load)
    except Exception as e:
        logging.error("Error in uploading exercise information in to DynamoDB: %s", e)
        raise

    return {"message": "Script Complete."}


def lambda_handler(event, context):
    """
    Docstring for lambda_handler

    :param event: variable passed through from previous function
    """

    try:
        setup_logging()
        logging.info("Handling and processing Lambda event..")
        logging.debug("Debug: Event information: %s", event)
        logging.debug("Debug: Type: %s", type(event))

        if isinstance(event, str):
            event = json.loads(event)

        for item in event["Records"]:
            body = item.get("body")

            if body:
                data = json.loads(body)

        logging.debug("Debug: The message body data type, prior to transformation: %s", type(data))

        if isinstance(data, str):
            data = json.loads(data)

        logging.debug("Debug: The message body data type, post transformation: %s", type(data))

        exerciseId = data.get("entity_id")

        logging.debug("Debug: Exercise ID: %s", exerciseId)

        return run_app(exerciseId=exerciseId)

    except Exception as e:
        logging.error("Error in extracting information from event from SNS: %s", e)
        raise


if __name__ == "__main__":
    event = os.environ["EXAMPLE_EVENT"]
    lambda_handler(event, None)
