"""Exceptions for the project."""
class OutputFormatError(Exception):
    """Exception raised for errors in the LLM output format."""


class FineTuningFailedError(Exception):
    """Exception raised when fine-tuning job is failed or cancelled."""


class BatchModeFailedError(Exception):
    """Exception raised when batch mode is not supported for the model."""
