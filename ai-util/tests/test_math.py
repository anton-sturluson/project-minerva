from aitoolkit import math
import numpy as np


def test_shannon_index():
    arr1 = [0.2, 0.3, 0.5]
    index1 = math.shannon_index(arr1)
    assert np.isclose(index1, 1.0297, atol=1e-4), index1

    arr2 = [0.5, 0, 0.5]
    index2 = math.shannon_index(arr2)
    assert np.isclose(index2, 0.6932, atol=1e-4), index2

    arr3 = [0., 0, 0.]
    index3 = math.shannon_index(arr3)
    assert index3 == 0, index3

    arr4 = [0.3, 0.3, 0.4]
    index4 = math.shannon_index(arr4)
    assert np.isclose(index4, 1.0889, atol=1e-4), index4
