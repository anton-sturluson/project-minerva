"""Abstract hyperparameter tuning module."""
__all__ = ["HyperparameterTuner", "TuningConfig"]

from dataclasses import dataclass
from itertools import product
from typing import Any, Callable

import numpy as np
from tqdm import tqdm


@dataclass
class TuningConfig:
    performance: float
    params: dict[str, Any]


class HyperparameterTuner:
    """
    Hyperparameter tuning class. Given a search space and a performance
    evaluation function, this class runs a parameter sweep across the search
    space and saves the performance with every configuration, sorted
    descendingly from the best to worst performance.

    Attrs:
        search_space: dictionary where keys are parameter names and values
                      are lists of values to try during the parameter sweep.
        performance_fn: function to evaluate performance of the configuration.
            if None, the tuner will default to using `self.performance_fn`.
            If the function is not implemented, the tuner will raise an error.
        config_lst: list of configurations tried and their performance.
    """
    def __init__(
        self,
        search_space: dict[str, list[Any]],
        performance_fn: Callable | None = None
    ):
        self.search_space = search_space
        if performance_fn:
            self.get_performance = performance_fn
        self.configs = []

    def sweep(
        self, data: list[Any], save_results: bool = True
    ) -> TuningConfig | None:
        """Run parameter sweep and return the best config."""
        param_names = list(self.search_space.keys())
        param_values = list(self.search_space.values())
        config_lst = []

        for param_combination in tqdm(self.init_search_space(param_values)):
            params = dict(zip(param_names, param_combination))
            performance = self.get_performance(data=data, **params)
            config = TuningConfig(performance, params)
            config_lst.append(config)

        config_lst = sorted(
            config_lst, key=lambda x: x.performance, reverse=True)
        if save_results:
            self.configs = config_lst

        if config_lst:
            return config_lst[0]
        return None

    def cross_validate(
        self,
        data: Any,
        k: int = 5,
        seed: int = 42,
        data_split_fn: Callable | None = None
    ) -> float:
        """
        Run k-fold cross validation.

        Args:
            data: dataset to be used for cross-validation.
            k: number of folds.
            seed: random seed for reproducibility.
            data_split_fn: function to split the data into training and
                validation sets. Should take data, fold index, and total
                number of folds as arguments and return a tuple
                (train_data, val_data).

        Returns:
            Average cross-validation performance.
        """
        np.random.seed(seed)
        indices = np.arange(len(data))
        np.random.shuffle(indices)
        folds = np.array_split(indices, k)

        avg_performance = 0
        for i, val_indices in enumerate(folds):
            if data_split_fn is None:
                train_indices = np.hstack([folds[j] for j in range(k) if j != i])
                train_data, val_data = data[train_indices], data[val_indices]
            else:
                train_data, val_data = data_split_fn(data, i, k)

            config_lst = self.sweep(save_results=False)
            best_params = config_lst[0].params

            train_performance = self.get_performance(
                data=train_data, **best_params)
            val_performance = self.get_performance(
                data=val_data, **best_params)

            avg_performance += (val_performance - train_performance) / k

        return avg_performance

    def init_search_space(self, param_values: list[list[Any]]) -> iter:
        """Initialize sweep search space."""
        return product(*param_values)

    def get_performance(self, data, *args, **kwargs) -> float:
        raise NotImplementedError

    @property
    def num_configs(self) -> int:
        """Return number of configs tried during the sweep."""
        return len(self.config_lst)

    @property
    def best_config(self) -> TuningConfig | None:
        """Return config with the best performance."""
        if self.config_lst:
            return self.config_lst[0]
        return None

    @property
    def sweep_finished(self) -> bool:
        return bool(self.config_lst)
