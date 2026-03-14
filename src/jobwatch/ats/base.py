"""Abstract base class for ATS clients."""

from __future__ import annotations

from abc import ABC, abstractmethod

from jobwatch.models import FetchResult


class ATSClient(ABC):
    """Base class for ATS API adapters."""

    def __init__(self, board_slug: str):
        self.board_slug: str = board_slug

    @abstractmethod
    def fetch_all(self) -> FetchResult:
        """Fetch all job postings from the ATS.

        Returns FetchResult with normalized postings, exhaustiveness flag,
        and a response hash for change detection.
        """
        ...
