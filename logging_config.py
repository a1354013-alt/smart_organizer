from __future__ import annotations

import logging
import logging.config
import os


def setup_logging() -> None:
    """
    Minimal but production-friendly logging setup.

    - Idempotent: safe to call on every Streamlit rerun.
    - User-facing UI should remain friendly; detailed traces go to logs.
    """

    if getattr(setup_logging, "_configured", False):
        return

    level_name = (os.getenv("LOG_LEVEL") or "INFO").upper().strip()
    level = getattr(logging, level_name, logging.INFO)

    handlers: dict[str, dict[str, object]] = {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
            "level": level,
        }
    }
    root_handlers = ["console"]

    # Optional file logging for supportability (disabled by default).
    log_file = (os.getenv("LOG_FILE") or "").strip()
    if log_file:
        try:
            log_dir = os.path.dirname(os.path.abspath(log_file))
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)
            handlers["file"] = {
                "class": "logging.FileHandler",
                "formatter": "standard",
                "level": level,
                "filename": log_file,
                "encoding": "utf-8",
            }
            root_handlers.append("file")
        except Exception:
            # Don't fail app startup due to log path issues.
            pass

    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "standard": {
                    "format": "%(asctime)s %(levelname)s %(name)s - %(message)s",
                }
            },
            "handlers": handlers,
            "root": {
                "handlers": root_handlers,
                "level": level,
            },
        }
    )

    setup_logging._configured = True  # type: ignore[attr-defined]
