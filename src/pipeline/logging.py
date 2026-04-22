"""Structured logging configuration using structlog."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import structlog


def setup_logging(level: int = logging.INFO, json_output: bool = True) -> None:
    """Configure structlog with JSON or console output."""
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]
    if json_output:
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Configure shioaji logger to write to data/logs/shioaji.log
    log_dir = Path(__file__).resolve().parent.parent.parent / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    sj_handler = logging.FileHandler(log_dir / "shioaji.log")
    sj_handler.setFormatter(formatter)
    sj_logger = logging.getLogger("shioaji")
    sj_logger.handlers.clear()
    sj_logger.addHandler(sj_handler)
    sj_logger.setLevel(logging.DEBUG)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a structlog bound logger for a module."""
    bound_logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return bound_logger
