"""Matplotlib chart utilities: themes, save helper, axis formatters."""

from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
from matplotlib.figure import Figure

THEME_LIGHT: dict[str, Any] = {
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "axes.grid": True,
    "grid.alpha": 0.3,
    "font.size": 11,
    "axes.titlesize": 14,
    "axes.titleweight": "bold",
}

THEME_DARK: dict[str, Any] = {
    "figure.facecolor": "#0e1117",
    "axes.facecolor": "#0e1117",
    "axes.edgecolor": "#333",
    "axes.labelcolor": "#ccc",
    "axes.titlesize": 13,
    "axes.titleweight": "bold",
    "text.color": "#ccc",
    "xtick.color": "#999",
    "ytick.color": "#999",
    "grid.color": "#222",
    "grid.alpha": 0.6,
    "legend.facecolor": "#1a1a2e",
    "legend.edgecolor": "#333",
    "legend.fontsize": 9,
    "font.family": "sans-serif",
    "figure.dpi": 150,
}


def apply_theme(theme: dict[str, Any] | None = None):
    """Apply a matplotlib rcParams theme. Defaults to THEME_LIGHT."""
    if theme is None:
        theme = THEME_LIGHT
    plt.rcParams.update(theme)


def save_fig(
    fig: Figure, path: str | Path, dpi: int = 150, close: bool = True
):
    """Save a matplotlib figure and optionally close it."""
    fig.savefig(path, dpi=dpi, bbox_inches="tight")
    if close:
        plt.close(fig)


def axis_formatter_millions(x: float, pos: int = 0) -> str:
    """Axis tick formatter: '$X,XXXM'."""
    return f"${x / 1_000_000:,.0f}M"


def axis_formatter_billions(x: float, pos: int = 0) -> str:
    """Axis tick formatter: '$X.XB'."""
    return f"${x / 1_000_000_000:.1f}B"


def axis_formatter_pct(x: float, pos: int = 0) -> str:
    """Axis tick formatter: 'X%'."""
    return f"{x:.0f}%"
