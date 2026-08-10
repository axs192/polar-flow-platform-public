"""Entry point: launch the web app with uvicorn.

Run with:  uv run python -m src.main
"""

import uvicorn

from .config import settings
from .logging_config import setup_logging


def main() -> None:
    setup_logging()
    uvicorn.run(
        "src.app:app",
        host=settings.host,
        port=settings.port,
        reload=True,
        # Only watch source. Without this the reloader also watches logs/, so
        # every log write triggers a restart (and a watchfiles "change detected"
        # log, which writes again → a feedback loop that floods the log and
        # keeps the server perpetually reloading).
        reload_dirs=["src"],
    )


if __name__ == "__main__":
    main()
