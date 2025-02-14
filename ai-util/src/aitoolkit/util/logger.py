"""Configure logger for the project."""
from datetime import datetime
import logging
from os import path, makedirs
from pathlib import Path


def configure_logger(logger_name: str):
    """Configure logger"""
    # decide where to save the log
    log_dir = Path("../logs")
    if not path.exists(log_dir):
        makedirs(log_dir)
    log_path = log_dir / datetime.today().strftime("%Y-%m-%d.log")

    # initialize main logger
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.DEBUG)

    # decide format of the log
    format_ = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    formatter = logging.Formatter(format_)

    # FileHandler to save in log_path
    fh = logging.FileHandler(log_path)
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    # StreamHandler to print out log in stdout
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    return logger
