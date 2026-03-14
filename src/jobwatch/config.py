"""Company registry and settings for JobWatch."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from jobwatch.models import ATSType


@dataclass(frozen=True)
class CompanyConfig:
    """Configuration for a target company."""

    id: str
    name: str
    ats_type: ATSType
    ats_board: str
    website: str | None = None


COMPANY_REGISTRY: list[CompanyConfig] = [
    CompanyConfig(
        id="anthropic",
        name="Anthropic",
        ats_type=ATSType.GREENHOUSE,
        ats_board="anthropic",
        website="https://anthropic.com",
    ),
    CompanyConfig(
        id="xai",
        name="xAI",
        ats_type=ATSType.GREENHOUSE,
        ats_board="xai",
        website="https://x.ai",
    ),
    CompanyConfig(
        id="openai",
        name="OpenAI",
        ats_type=ATSType.ASHBY_SSR,
        ats_board="openai",
        website="https://openai.com",
    ),
    CompanyConfig(
        id="cursor",
        name="Cursor",
        ats_type=ATSType.ASHBY,
        ats_board="cursor",
        website="https://cursor.com",
    ),
    CompanyConfig(
        id="cognition",
        name="Cognition",
        ats_type=ATSType.ASHBY,
        ats_board="cognition",
        website="https://cognition.ai",
    ),
]


@dataclass
class Settings:
    """JobWatch runtime settings."""

    db_path: Path = field(default_factory=lambda: Path("data/jobwatch.db"))
    taxonomy_version: str = "v1"
    prompt_version: str = "v1"


def get_company(company_id: str) -> CompanyConfig:
    """Look up a company by id."""
    for company in COMPANY_REGISTRY:
        if company.id == company_id:
            return company
    raise ValueError(f"Unknown company: {company_id}")
