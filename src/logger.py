"""Centralized logging configuration for AI Internship Application Agent."""
import logging
import os
from pathlib import Path


def get_logger(name: str = "internship_agent") -> logging.Logger:
    """Return a configured logger writing to both console and file."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_str, logging.INFO)
    logger.setLevel(log_level)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    log_file = os.getenv("LOG_FILE_PATH", "logs/agent.log")
    try:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception as exc:
        logger.warning("Failed to initialize file logger at %s: %s", log_file, exc)

    logger.propagate = False
    return logger
