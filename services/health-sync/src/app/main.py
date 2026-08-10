"""
Main Module that is run for the application. Calls Helper functions to
executre two tasks -> Send a summary message to a user, and upload their latest
data into S3 and Dynamo DB
"""

import logging

from src.app.helpers.daily_helper import Daily_Helper
from src.app.helpers.logging_config import setup_logging


def run_app():
    """
    Docstring for run_app

    :param event: this is the lambda event
    """
    try:
        setup_logging()
        logging.info("Successfully intitited logging.")
    except Exception as e:
        logging.error("Error setting up logging: %s", e)
        raise

    # Upload runs before notification, deliberately - upload_daily_load's
    # DynamoDB write is a keyed overwrite (safe/idempotent to retry) and its
    # backfill loop resumes from wherever it left off, so a retry of this
    # whole invocation never duplicates data. Notification is last so a
    # message is only deleted from SQS (no retry) once the notification has
    # actually sent - a successful notification is never retried/resent, but
    # a failed one raises and gets retried on the next attempt.
    try:
        Daily_Helper().upload_daily_load()
    except Exception as e:
        logging.error("Error in uploading daily load to DynamoDB: %s", e)
        raise

    try:
        Daily_Helper().send_daily_notification()
    except Exception as e:
        logging.error("Error sending daily notificaiton: %s", e)
        raise

    return {"message": "Script Complete."}


def lambda_handler(event, context):
    """
    Docstring for lambda_handler

    :param event: variable passed through from previous function
    """

    return run_app()


if __name__ == "__main__":
    lambda_handler({}, None)
