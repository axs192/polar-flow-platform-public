import logging
import os

import boto3


def get_prompt(exercise: bool = False, health: bool = False) -> str:
    """Return the system prompt text for a query, from S3.

    Parameters
    ----------
    exercise : bool, optional
        Use the exercise-focused prompt.
    health : bool, optional
        Use the health-focused prompt.
    """
    try:
        s3 = boto3.client("s3")
        bucket_name = os.environ["BUCKET_NAME"]
        if health:
            file_path = os.environ["HEALTH_PROMPT_PATH"]
        if exercise:
            file_path = os.environ["EXERCISE_PROMPT_PATH"]
        response = s3.get_object(Bucket=bucket_name, Key=file_path)
        return response["Body"].read().decode("utf-8")
    except Exception as e:
        logging.error("Error getting the prompt from S3 bucket: %s", e)
        raise
