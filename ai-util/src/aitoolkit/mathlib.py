import numpy as np


def pad_percentile(arr, percentile, len_):
    """Pad vector g with 0s to len_ and take q-th percentile.

    Args:
        g: A vector of floats ranging [0, 1]
        percentile: A percentile
        len_: The length of the padded vector

    Returns:
        The q-th percentile of the padded vector
    """
    padded_arr = np.pad(arr, (0, len_ - len(arr)))
    return np.percentile(padded_arr, percentile)


def pad_median(arr, len_):
    """Pad vector g with 0s to len_ and take the median.

    Args:
        arr: A vector of floats ranging [0, 1]
        len_: The length of the padded vector

    Returns:
        The median of the padded vector
    """
    padded_arr = np.pad(arr, (0, len_ - len(arr)))
    return np.median(padded_arr)


def minmax(v_1, v_2, v_3):
    """Return minimum of v_3 and maximum of v_1 and v_2."""
    return min(v_3, max(v_1, v_2))


def maxmin(v_1, v_2, v_3):
    """Return maximum of v_3 and minimum of v_1 and v_2."""
    return max(v_3, min(v_1, v_2))


def inv_simpson(arr: np.ndarray | list[float]) -> float:
    """Calculate Inverse-Simpson index."""
    if sum(arr) == 0:
        return 0

    if isinstance(arr, list):
        arr = np.array(arr)

    return 1 / (arr ** 2).sum()


def shannon_index(arr: np.ndarray[float] | list[float]) -> float:
    """
    Compute shannon index using a given array of relative abundances.
    Shannon Index: -\\sum_{i=1}^R p_i ln(p_i)
    """
    if sum(arr) == 0:
        return 0

    if isinstance(arr, list):
        arr = np.array(arr)

    n = len(arr)
    # log-transform while ignoring 0 values
    log_arr = np.log(
        arr, out=np.zeros_like(arr, dtype=np.float64), where=arr!=0)
    return -(arr * log_arr).sum()


def standardize(
    x: float | np.ndarray, mean: float, std: float
) -> float | np.ndarray:
    """
    Standardize `x` given mean and standard deviation. if standard
    deviation is zero, returns `x` unchanged.
    """
    if not std:
        return x
    return (x - mean) / std


def normalize(arr: np.ndarray | list[float]) -> np.ndarray:
    """Normalize array to sum upto 1."""
    if not isinstance(arr, np.ndarray):
        arr = np.array(arr)
    arr_sum: float = arr.sum()
    if arr_sum == 0:
        return arr
    return arr / arr_sum
