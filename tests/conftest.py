"""Shared fixtures for minerva tests."""

import pytest
from pathlib import Path


@pytest.fixture
def tmp_dir(tmp_path: Path) -> Path:
    """Provide a temporary directory for file-based tests."""
    return tmp_path
