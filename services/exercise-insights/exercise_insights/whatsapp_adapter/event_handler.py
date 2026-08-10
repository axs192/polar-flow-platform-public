import contextlib
import json
import logging


def extract_sqs_message(event) -> str:
    """Extract the text body from an SQS-triggered Lambda event."""
    try:
        if isinstance(event, str):
            try:
                event = json.loads(event)
            except json.JSONDecodeError:
                return str(event)

        for record in event.get("Records", []):
            body = record.get("body")
            if not body:
                continue
            with contextlib.suppress(json.JSONDecodeError):
                body = json.loads(body)
            return str(body)

        return ""
    except Exception as e:
        logging.error("Error extracting SQS message: %s", e)
        return ""
