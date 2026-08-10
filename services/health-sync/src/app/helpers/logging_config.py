"""
Configure the logging settings
"""

import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def setup_logging() -> None:
    # Determine if running in AWS Lambda
    RUNNING_IN_LAMBDA = os.environ.get("AWS_LAMBDA_FUNCTION_NAME") is not None

    # Get log level from environment
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    numeric_level = getattr(logging, log_level, logging.INFO)

    # Configure root logger
    logger = logging.getLogger()
    logger.setLevel(numeric_level)

    # Clear existing handlers
    if logger.hasHandlers():
        logger.handlers.clear()
    if RUNNING_IN_LAMBDA:
        handler = logging.StreamHandler(sys.stdout)
    else:
        LOG_FILE = Path(__file__).parents[3] / "logs" / "app.log"
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(LOG_FILE)

    format = logging.Formatter("%(asctime)s %(name)s [%(levelname)s] %(message)s")
    handler.setFormatter(format)
    logger.addHandler(handler)
