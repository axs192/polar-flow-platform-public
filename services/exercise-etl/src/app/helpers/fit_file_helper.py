import logging
from pathlib import Path

from fitparse import FitFile


def _normalise_fit_value(value):
    """Convert FIT values into JSON-serialisable values."""

    if isinstance(value, (list, tuple)):
        return [_normalise_fit_value(item) for item in value]

    if isinstance(value, dict):
        return {key: _normalise_fit_value(item) for key, item in value.items()}

    if hasattr(value, "isoformat"):
        return value.isoformat()

    return value


def load_fit_session_dataframe(filename) -> dict:
    """Load FIT session messages and return them as a pandas DataFrame."""

    try:
        file_path = Path(filename)

        if not file_path.exists():
            raise FileNotFoundError("FIT file not found: %s", {file_path})

        fit_file = FitFile(str(file_path))

        for session in fit_file.get_messages("session"):
            data = {d.name: _normalise_fit_value(d.value) for d in session}

        return data

    except Exception as e:
        logging.error("Failed to get session data from fit file: %s", {e})
        raise
