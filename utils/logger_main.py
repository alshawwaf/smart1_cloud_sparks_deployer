"""Logging for the deployer: rotating log file, console output and secret redaction"""
import logging
from pathlib import Path
from typing import Iterable, Optional
from logging.handlers import RotatingFileHandler

def configure_logging() -> logging.Logger:
    """Configure logging system with file rotation and console output"""
    log_dir = Path("logs")
    log_file = log_dir / "s1c_deploy_sparks_gw.log"

    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError as e:
        raise RuntimeError(f"Unable to create logs directory: {str(e)}") from e

    logger = logging.getLogger("Smart1CloudDeployer")
    logger.setLevel(logging.DEBUG)

    # File handler with rotation
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=5*1024*1024,  # 5MB
        backupCount=3,
        encoding='utf-8'
    )
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(file_formatter)
    file_handler.setLevel(logging.DEBUG)

    # Console handler
    console_handler = logging.StreamHandler()
    console_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    console_handler.setFormatter(console_formatter)
    console_handler.setLevel(logging.INFO)

    # Add handlers
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger


REDACTED = "********"


def redact(text: str, secrets: Iterable[Optional[str]]) -> str:
    """Replace every secret value in text before it is logged"""
    for secret in secrets:
        if secret:
            text = text.replace(secret, REDACTED)
    return text

log = configure_logging()
