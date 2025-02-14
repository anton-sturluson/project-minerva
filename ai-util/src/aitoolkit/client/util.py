"""Utility functions for LLM clients."""
import logging
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
    retry_if_not_exception_type
)

logger = logging.getLogger(__name__)

def retry_with_backoff(
    no_retry_exceptions: tuple[str] = (
        ValueError,
        KeyError,
        TypeError
    ),
    min_wait: float = 2,
    max_wait: float = 32,
    max_attempts: int = 5,
    multiplier: float = 2
):
    """Retry decorator with exponential backoff.
    
    Args:
        no_retry_exceptions: Exception or tuple of exceptions that should not trigger retry
        max_attempts: Maximum number of retry attempts
        min_wait: Minimum wait time between retries in seconds
        max_wait: Maximum wait time between retries in seconds
        
    Returns:
        Retry decorator that retries on all errors except specified exceptions
    """
    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=multiplier, min=min_wait, max=max_wait),
        retry=retry_if_not_exception_type(no_retry_exceptions),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True
    )
