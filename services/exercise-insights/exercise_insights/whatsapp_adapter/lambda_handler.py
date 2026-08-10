import logging
import os

from exercise_insights.core.answer import answer_question
from exercise_insights.shared.logging_config import setup_logging
from exercise_insights.whatsapp_adapter.event_handler import extract_sqs_message
from exercise_insights.whatsapp_adapter.push_notification import Push_Notification


def lambda_handler(event, context):
    try:
        setup_logging()
    except Exception as e:
        logging.error("Error setting up logging: %s", e)
        raise

    logging.debug(event)

    try:
        question = extract_sqs_message(event)

        if isinstance(question, str) and question.strip():
            logging.info("User question: %s", question)
            # Single-tenant today: the WhatsApp conversation maps to one
            # fixed Polar user id, set here rather than buried in core logic
            # (see src/core/answer.py's answer_question signature) - this is
            # the seam that would change if this ever supports multiple users.
            user_id = os.environ["POLAR_USER_ID"]
            response = answer_question(user_id=user_id, question=question)
            Push_Notification().send_note(message=response)

    except Exception as e:
        logging.error("Error when handling event/processing event: %s", e)
        raise


if __name__ == "__main__":
    lambda_handler({}, None)
