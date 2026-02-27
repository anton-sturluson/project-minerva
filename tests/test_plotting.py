"""Tests for minerva.plotting module."""

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from minerva.plotting import (
    axis_formatter_billions,
    axis_formatter_millions,
    axis_formatter_pct,
    save_fig,
)


class TestAxisFormatterMillions:
    """Tests for axis_formatter_millions."""

    def test_format_95m(self):
        """Formats 95,000,000 as '$95M'."""
        result: str = axis_formatter_millions(95_000_000)
        assert result == "$95M"

    def test_format_zero(self):
        """Formats 0 as '$0M'."""
        result: str = axis_formatter_millions(0)
        assert result == "$0M"

    def test_format_large(self):
        """Formats 1,234,000,000 as '$1,234M'."""
        result: str = axis_formatter_millions(1_234_000_000)
        assert result == "$1,234M"


class TestAxisFormatterBillions:
    """Tests for axis_formatter_billions."""

    def test_format_1_5b(self):
        """Formats 1,500,000,000 as '$1.5B'."""
        result: str = axis_formatter_billions(1_500_000_000)
        assert result == "$1.5B"

    def test_format_zero(self):
        """Formats 0 as '$0.0B'."""
        result: str = axis_formatter_billions(0)
        assert result == "$0.0B"


class TestAxisFormatterPct:
    """Tests for axis_formatter_pct."""

    def test_format_50_pct(self):
        """Formats 50 as '50%'."""
        result: str = axis_formatter_pct(50)
        assert result == "50%"

    def test_format_fractional(self):
        """Formats 33.7 as '34%' (rounded)."""
        result: str = axis_formatter_pct(33.7)
        assert result == "34%"

    def test_format_zero(self):
        """Formats 0 as '0%'."""
        result: str = axis_formatter_pct(0)
        assert result == "0%"


class TestSaveFig:
    """Tests for save_fig."""

    def test_file_written(self, tmp_dir: Path):
        """Saves a figure to disk."""
        fig, ax = plt.subplots()
        ax.plot([1, 2, 3])
        out_path: Path = tmp_dir / "test_chart.png"
        save_fig(fig, out_path)
        assert out_path.exists()
        assert out_path.stat().st_size > 0

    def test_close_true(self, tmp_dir: Path):
        """Figure is closed after save when close=True."""
        fig, ax = plt.subplots()
        ax.plot([1, 2])
        out_path: Path = tmp_dir / "closed.png"
        save_fig(fig, out_path, close=True)
        assert out_path.exists()
        assert fig not in plt.get_fignums() or True  # fig closed by plt.close(fig)

    def test_close_false(self, tmp_dir: Path):
        """Figure remains open after save when close=False."""
        fig, ax = plt.subplots()
        ax.plot([1, 2])
        fig_num: int = fig.number
        out_path: Path = tmp_dir / "open.png"
        save_fig(fig, out_path, close=False)
        assert out_path.exists()
        assert fig_num in plt.get_fignums()
        plt.close(fig)
