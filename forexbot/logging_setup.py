"""Shared logging configuration: pretty console output + a rolling file log."""

from __future__ import annotations

import logging
from pathlib import Path

_LOG_FILE = Path(__file__).resolve().parent.parent / "bot.log"


def setup_logging(level: int = logging.INFO) -> None:
    fmt = "%(asctime)s %(levelname)-7s %(name)s | %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    root = logging.getLogger()
    if root.handlers:  # avoid duplicate handlers on re-import
        return
    root.setLevel(level)

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(fmt, datefmt))
    root.addHandler(console)

    file_handler = logging.FileHandler(_LOG_FILE)
    file_handler.setFormatter(logging.Formatter(fmt, datefmt))
    root.addHandler(file_handler)
