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


class FixedCountSelector:
    """Select fixed number of thresholds with max density in equal ranges."""

    def __init__(self, num_levels: int):
        """
        Initialize fixed count selector.

        Args:
            num_levels: Number of hierarchical levels to create
        """
        self.num_levels: int = num_levels

    def select(
        self, list_D: list[tuple[float, float]], linkage: list[tuple[int, int, float]]
    ) -> list[float]:
        """Divide similarity range into equal segments, pick max D in each."""
        if not list_D or self.num_levels <= 0:
            return []

        similarities: list[float] = [s for s, _ in list_D]
        min_S: float = min(similarities)
        max_S: float = max(similarities)

        if min_S == max_S:
            return [min_S]

        range_size: float = (max_S - min_S) / self.num_levels
        selected: list[tuple[float, float]] = []

        for i in range(self.num_levels):
            range_start: float = min_S + i * range_size
            range_end: float = range_start + range_size

            in_range: list[tuple[float, float]] = [
                (s, d) for s, d in list_D if range_start <= s < range_end
            ]

            if not in_range and i == self.num_levels - 1:
                in_range = [(s, d) for s, d in list_D if s >= range_start]

            if in_range:
                best: tuple[float, float] = max(in_range, key=lambda x: x[1])
                selected.append(best)

        thresholds: list[float] = sorted([s for s, _ in selected], reverse=True)
        return thresholds


class PercentileSelector:
    """Select thresholds at percentiles of similarity distribution."""

    def __init__(self, percentiles: list[float]):
        """
        Initialize percentile selector.

        Args:
            percentiles: List of percentiles (0-100), e.g., [25, 50, 75]
        """
        self.percentiles: list[float] = sorted(percentiles)

    def select(
        self, list_D: list[tuple[float, float]], linkage: list[tuple[int, int, float]]
    ) -> list[float]:
        """Select thresholds at specified percentiles of similarity values."""
        if not list_D:
            return []

        similarities: list[float] = sorted([s for s, _ in list_D], reverse=True)

        thresholds: list[float] = []
        for p in self.percentiles:
            idx: int = int(len(similarities) * p / 100.0)
            idx = min(idx, len(similarities) - 1)
            thresholds.append(similarities[idx])

        return sorted(set(thresholds), reverse=True)


class SimilarityGapSelector:
    """Select thresholds at large gaps in similarity during merging."""

    def __init__(self, min_gap: float = 0.1, top_k: int | None = None):
        """
        Initialize similarity gap selector.

        Args:
            min_gap: Minimum similarity difference to consider a gap
            top_k: Keep only top K largest gaps (optional)
        """
        self.min_gap: float = min_gap
        self.top_k: int | None = top_k

    def select(
        self, list_D: list[tuple[float, float]], linkage: list[tuple[int, int, float]]
    ) -> list[float]:
        """Find large jumps in similarity values during merging."""
        if len(linkage) < 2:
            return []

        gaps: list[tuple[float, float]] = []

        for i in range(len(linkage) - 1):
            _, _, S_curr = linkage[i]
            _, _, S_next = linkage[i + 1]

            gap: float = abs(S_next - S_curr)
            if gap >= self.min_gap:
                gaps.append((S_curr, gap))

        if self.top_k is not None and len(gaps) > self.top_k:
            gaps = sorted(gaps, key=lambda x: x[1], reverse=True)[: self.top_k]

        thresholds: list[float] = sorted([s for s, _ in gaps], reverse=True)
        return thresholds


class CommunityCountSelector:
    """Select thresholds that produce target community counts."""

    def __init__(self, target_counts: list[int]):
        """
        Initialize community count selector.

        Args:
            target_counts: Desired number of communities per level, e.g., [5, 11, 23]
        """
        self.target_counts: list[int] = sorted(target_counts)

    def select(
        self, list_D: list[tuple[float, float]], linkage: list[tuple[int, int, float]]
    ) -> list[float]:
        """Select thresholds that approximately produce target community counts."""
        if not linkage:
            return []

        num_initial: int = max(max(c1, c2) for c1, c2, _ in linkage) + 1

        similarity_to_num_communities: dict[float, int] = {1.0: num_initial}

        num_communities: int = num_initial
        for cid1, cid2, similarity in linkage:
            num_communities -= 1
            similarity_to_num_communities[similarity] = num_communities

        selected: list[float] = []
        for target in self.target_counts:
            closest_similarity: float | None = None
            min_diff: int = float("inf")

            for s, count in similarity_to_num_communities.items():
                diff: int = abs(count - target)
                if diff < min_diff:
                    min_diff = diff
                    closest_similarity = s

            if closest_similarity is not None:
                selected.append(closest_similarity)

        return sorted(set(selected), reverse=True)
