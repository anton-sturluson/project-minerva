"""Module for file I/O operations.

This module provides functions for saving and loading data in batch.
"""
__all__ = ["save_in_batch", "load_in_batch"]

import os
import math
from pathlib import Path
from typing import Any

from concurrent.futures import ThreadPoolExecutor
from aitoolkit.fileio.file import File, S3Url


def _save_file(file_path: str | Path | S3Url | File, data_lst: list[any]):
    """Save a list of data samples to a file.

    Args:
        file_path: Path to save the file at
        data_lst: A list of data samples to save
    """
    if not isinstance(file_path, File):
        file_path = File(file_path)
    file_path.save(data_lst)


def save_in_batch(
    save_dir, data_lst,
    num_batches: int = 10,
    ext: str = "pkl"
):
    """Save a list of data samples in batch.

    Args:
        save_dir: Directory to save the files at
        data_lst: A list of data samples to save
        num_batches: Number of batches to save the data in
        ext: Extension name of the files to be saved
    """
    save_dir = File(save_dir)
    if save_dir.is_local and not save_dir.exists:
        save_dir.mkdir(parents=True)

    future_lst = []
    N = math.ceil(len(data_lst) / num_batches)
    with ThreadPoolExecutor() as executor:
        for i in range(num_batches):
            start, end = i*N, (i+1)*N
            batch_lst = data_lst[start:end]
            save_path = save_dir / f"sample_batch_{i}.{ext}"

            future = executor.submit(_save_file, save_path, batch_lst)
            future_lst.append(future)

    for future in future_lst:
        future.result()


def _load_file(file: File) -> any:
    """Load data samples from a file."""
    return file.load()


def load_in_batch(
    file_dir: str | Path,
    extensions=(".csv", ".pkl", ".tsv", ".jsonl", ".json")
) -> list[Any]:
    """Load data samples from files in batch and aggregate into one list.

    Args:
        file_dir: Directory to load the files from
        extensions: Allowed file extensions for the files to be l:aded
    """
    file_dir = File(file_dir)

    future_lst = []
    with ThreadPoolExecutor() as executor:
        for file in file_dir.list_files():
            if not file.endswith(extensions):
                continue
            future = executor.submit(_load_file, file)
            future_lst.append(future)

    data_lst = []
    for future in future_lst:
        result = future.result()
        if isinstance(result, list):
            data_lst.extend(result)
        else:
            data_lst.append(result)

    return data_lst
