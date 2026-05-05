"""Runtime configuration for the Minerva investment harness."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field


class HarnessSettings(BaseModel):
    """Environment-backed settings for Minerva CLI commands."""

    workspace_root: Path = Field(default_factory=lambda: Path("hard-disk"))
    edgar_identity: str | None = None
    parallel_api_key: str | None = None
    gemini_api_key: str | None = None
    openai_api_key: str | None = None
    finnhub_api_key: str | None = None
    minerva_plot_theme: str = "minerva-classic"

    @property
    def resolved_workspace_root(self) -> Path:
        """Return the absolute workspace root."""
        return self.workspace_root.resolve()

    def ensure_workspace_root(self) -> Path:
        """Create the workspace root if it does not exist yet."""
        root: Path = self.resolved_workspace_root
        root.mkdir(parents=True, exist_ok=True)
        return root


@lru_cache(maxsize=1)
def get_settings() -> HarnessSettings:
    """Load settings from environment variables once per process."""
    return HarnessSettings(
        workspace_root=Path(os.getenv("MINERVA_WORKSPACE_ROOT", "hard-disk")),
        edgar_identity=os.getenv("EDGAR_IDENTITY"),
        parallel_api_key=os.getenv("PARALLEL_API_KEY"),
        gemini_api_key=os.getenv("GEMINI_API_KEY"),
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        finnhub_api_key=os.getenv("FINNHUB_API_KEY"),
        minerva_plot_theme=os.getenv("MINERVA_PLOT_THEME", "minerva-classic"),
    )
