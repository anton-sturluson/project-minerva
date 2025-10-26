"""Logging configuration for Minerva."""

import logging
import sys
import inspect


class ClassNameFormatter(logging.Formatter):
    """Custom formatter that includes class name if available."""

    def format(self, record: logging.LogRecord) -> str:
        # Try to get the class name from the call stack
        class_name = None
        for frame_info in inspect.stack():
            frame_locals = frame_info.frame.f_locals
            if "self" in frame_locals:
                class_name = frame_locals["self"].__class__.__name__
                break
            elif "cls" in frame_locals:
                class_name = frame_locals["cls"].__name__
                break

        if class_name:
            record.className = class_name
            return super().format(record)
        else:
            record.className = ""
            return super().format(record)


def setup_logger(name: str = "minerva", level: int = logging.INFO) -> logging.Logger:
    """Set up a logger with consistent formatting.

    Format: [LEVEL] ClassName.function: message
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(level)

        formatter = ClassNameFormatter(
            fmt="[%(levelname)s] %(className)s.%(funcName)s: %(message)s"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger
