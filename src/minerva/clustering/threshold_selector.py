"""Threshold selection strategies for hierarchical clustering."""

from typing import Protocol

import numpy as np
from scipy.signal import find_peaks


class ThresholdSelector(Protocol):
    """Protocol for threshold selection strategies in hierarchical clustering."""

    def select(
        self, list_D: list[tuple[float, float]], linkage: list[tuple[int, int, float]]
    ) -> list[float]:
        """
        Select similarity thresholds for multi-level partitioning.

        Args:
            list_D: List of (similarity, partition_density) tuples from HLC
            linkage: List of (child1_cid, child2_cid, similarity) tuples

        Returns:
            List of similarity thresholds, sorted descending (most granular first)
        """
        ...


class LocalMaximaSelector:
    """Select thresholds at local maxima in partition density curve."""

    def __init__(self, min_prominence: float | None = None, top_k: int | None = None):
        """
        Initialize local maxima selector.

        Args:
            min_prominence: Minimum height above neighbors (optional)
            top_k: Keep only top K peaks by density (optional)
        """
        self.min_prominence: float | None = min_prominence
        self.top_k: int | None = top_k

    def select(
        self, list_D: list[tuple[float, float]], linkage: list[tuple[int, int, float]]
    ) -> list[float]:
        """Find local maxima in partition density curve using scipy.signal.find_peaks."""
        if len(list_D) < 3:
            return []

        densities: np.ndarray = np.array([d for _, d in list_D])

        peak_indices: list[int]
        peak_indices, _ = find_peaks(densities, prominence=self.min_prominence)

        peaks: list[tuple[float, float]] = [
            (list_D[i][0], list_D[i][1]) for i in peak_indices
        ]

        if self.top_k is not None and len(peaks) > self.top_k:
            peaks = sorted(peaks, key=lambda x: x[1], reverse=True)[: self.top_k]

        thresholds: list[float] = sorted([s for s, _ in peaks], reverse=True)
        return thresholds
