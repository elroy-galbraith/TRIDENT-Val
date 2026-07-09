"""Central loguru configuration.

Human-readable console output for developers, a rotating file for post-hoc
debugging, and a DB sink that persists INFO-and-above records into
`system_logs` so operational telemetry and the underwriter audit trail live
in the same place the frontend's logs do (see `main.log_client_event`).
"""
import sys
from pathlib import Path

from loguru import logger

from .db import SessionLocal
from .models import SystemLog

LOG_DIR = Path(__file__).resolve().parents[2] / "logs"

CONSOLE_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | "
    "<cyan>{name}</cyan> - <level>{message}</level>"
)
FILE_FORMAT = "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name} - {message}"


def _db_sink(message):
    """Persist a loguru record as a `system_logs` row.

    Runs on loguru's own enqueue thread (see setup_logging), so it never
    blocks the request path. Failures are swallowed on purpose: logging must
    never be able to take the API down.
    """
    record = message.record
    extra = record["extra"]
    try:
        db = SessionLocal()
        try:
            db.add(SystemLog(
                source=extra.get("source", "backend"),
                level=record["level"].name,
                logger_name=extra.get("logger_name") or record["name"] or "backend",
                message=record["message"],
                pid=extra.get("pid"),
                context=extra.get("context"),
            ))
            db.commit()
        finally:
            db.close()
    except Exception:
        pass


def setup_logging(console_level: str = "INFO", db_level: str = "INFO") -> None:
    logger.remove()  # drop loguru's default stderr sink so we control formatting

    logger.add(sys.stderr, level=console_level, format=CONSOLE_FORMAT, colorize=True)

    LOG_DIR.mkdir(exist_ok=True)
    logger.add(
        LOG_DIR / "backend.log",
        level="DEBUG",
        format=FILE_FORMAT,
        rotation="10 MB",
        retention="7 days",
        encoding="utf-8",
    )

    # enqueue=True hands DB writes off to a background thread so a slow insert
    # never adds latency to the request that triggered the log line.
    logger.add(_db_sink, level=db_level, enqueue=True, backtrace=False, diagnose=False)

    logger.info("Logging configured: console={console_level}, db={db_level}",
               console_level=console_level, db_level=db_level)
