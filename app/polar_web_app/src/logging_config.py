"""Central logging setup.

One call to :func:`setup_logging` configures the root logger to write to both
the console and a rotating file under the project's ``logs/`` directory, so you
can watch what the app is doing live (stdout) and keep a durable record on disk.

The log directory and file name come from :mod:`src.config` (``LOG_DIR`` /
``LOG_FILE`` / ``LOG_LEVEL`` env vars). The directory is created on first call.
``setup_logging`` is idempotent — calling it more than once (e.g. from both the
entry point and uvicorn's reloader) will not stack duplicate handlers.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import settings

# Project root is the parent of the ``src`` package, so ``logs/`` sits next to
# ``src/`` rather than inside it.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"

_configured = False


def log_path() -> Path:
    """Absolute path to the active log file (directory created if needed)."""
    log_dir = _PROJECT_ROOT / settings.log_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / settings.log_file


def setup_logging() -> None:
    """Configure root logging once: console + rotating file handlers."""
    global _configured
    if _configured:
        return

    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    formatter = logging.Formatter(_LOG_FORMAT)

    root = logging.getLogger()
    root.setLevel(level)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    # 1 MB per file, keep 5 backups — enough history without unbounded growth.
    file_handler = RotatingFileHandler(
        log_path(), maxBytes=1_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # Quiet chatty third-party loggers so they don't drown the app's own logs
    # even when the root level is DEBUG. watchfiles logs a line per file change;
    # the httpx/httpcore/hpack stack logs every byte of the Supabase HTTP call.
    for noisy in (
        "watchfiles",
        "uvicorn.access",
        "httpx",
        "httpcore",
        "hpack",
        "asyncio",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _configured = True
    logging.getLogger(__name__).info(
        "Logging configured at level %s -> %s", settings.log_level.upper(), log_path()
    )
