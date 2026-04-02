"""Runtime configuration for the Minerva investment harness."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field


class HarnessSettings(BaseModel):
    """Workspace and provider configuration loaded from environment variables."""

    workspace_root: Path = Field(default_factory=lambda: Path("hard-disk"))
    llm_provider: str = "anthropic"
    llm_model: str = "anthropic/claude-sonnet-4-20250514"
    delegate_model: str = "anthropic/claude-haiku-4-5-20251001"
    anthropic_api_key: str | None = None
    brave_api_key: str | None = None

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
        llm_provider=os.getenv("MINERVA_LLM_PROVIDER", "anthropic"),
        llm_model=os.getenv("MINERVA_LLM_MODEL", "anthropic/claude-sonnet-4-20250514"),
        delegate_model=os.getenv("MINERVA_DELEGATE_MODEL", "anthropic/claude-haiku-4-5-20251001"),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
        brave_api_key=os.getenv("BRAVE_API_KEY"),
    )
