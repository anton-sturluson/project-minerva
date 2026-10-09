"""Verify exact report-quarter windows and existing database investor selection."""

import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

from investor_platform.db import LOCAL_WORKSPACE
from investor_platform.models import Owner, ResearchFiling, ResearchManager, Workspace
from investor_platform.research_sync import quarter_window, submission_rows


@pytest.mark.parametrize(
    ("count", "through", "first", "last"),
    [
        (20, "2026-Q2", "2021-09-30", "2026-06-30"),
        (1, "2024-Q1", "2024-03-31", "2024-03-31"),
        (2, "2024-Q1", "2023-12-31", "2024-03-31"),
        (4, "2024-Q1", "2023-06-30", "2024-03-31"),
        (20, "2023-Q4", "2019-03-31", "2023-12-31"),
    ],
)
def test_exact_inclusive_window(count: int, through: str, first: str, last: str) -> None:
    """Calendar quarter arithmetic includes both endpoints and crosses years correctly."""
    assert quarter_window(count, through, date(2026, 10, 8)) == (
        date.fromisoformat(first),
        date.fromisoformat(last),
    )


@pytest.mark.parametrize(
    ("count", "through"),
    [
        (0, "2026-Q2"),
        (-1, "2026-Q2"),
        (20, "2026-Q5"),
        (20, "2026-06-30"),
        (20, "2027-Q1"),
        (20, "1999-Q2"),
        (1000000000, "2026-Q2"),
    ],
)
def test_invalid_windows_fail_before_collection(count: int, through: str) -> None:
    """Invalid or future windows cannot broaden collection silently."""
    with pytest.raises(ValueError):
        quarter_window(count, through, date(2026, 10, 8))


def test_submission_rows_keep_only_inclusive_report_periods() -> None:
    """Metadata outside either endpoint is removed before any filing document is fetched."""
    data: dict = {
        "form": ["13F-HR", "13F-HR/A", "13F-HR", "13F-HR", "13F-HR", "13F-NT"],
        "reportDate": [
            "2021-06-30",
            "2021-09-30",
            "2025-12-31",
            "2026-06-30",
            "2026-09-30",
            "2026-06-30",
        ],
        "accessionNumber": ["older", "first", "middle", "last", "newer", "notice"],
        "filingDate": ["2026-10-01"] * 6,
        "primaryDocument": ["primary.xml"] * 6,
    }
    start: date
    end: date
    start, end = quarter_window(20, "2026-Q2", date(2026, 10, 8))
    rows: list[dict] = submission_rows(data, 2021, start_period=start, end_period=end)
    assert [row["accession"] for row in rows] == ["first", "middle", "last"]
    assert rows[0]["form"] == "13F-HR/A"


def test_bounded_cli_preserves_database_roster_and_counts_exact_scope(database: Engine) -> None:
    """The real CLI reads owned stored investors without seeding or changing catalog metadata."""
    with Session(database) as session:
        alpha: ResearchManager = ResearchManager(
            workspace_id=LOCAL_WORKSPACE,
            slug="custom-alpha",
            cik="1001",
            profile={"name": "Custom Alpha"},
        )
        beta: ResearchManager = ResearchManager(
            workspace_id=LOCAL_WORKSPACE,
            slug="custom-beta",
            cik="1002",
            profile={"name": "Custom Beta"},
        )
        other_owner: UUID = uuid4()
        other_workspace: UUID = uuid4()
        session.add(Owner(id=other_owner))
        session.flush()
        session.add(Workspace(id=other_workspace, owner_id=other_owner))
        session.flush()
        foreign: ResearchManager = ResearchManager(
            workspace_id=other_workspace,
            slug="foreign",
            cik="1003",
            profile={"name": "Foreign Example"},
        )
        session.add_all([alpha, beta, foreign])
        session.flush()
        alpha_id: UUID = alpha.id
        period: str
        status: str
        for period, status in [
            ("2021-06-30", "complete"),
            ("2021-09-30", "complete"),
            ("2023-09-30", "blocked"),
            ("2026-06-30", "complete"),
            ("2026-09-30", "blocked"),
        ]:
            session.add(
                ResearchFiling(
                    manager_id=alpha.id,
                    accession=period,
                    report_period=date.fromisoformat(period),
                    filed_date=date(2026, 10, 1),
                    form="13F-HR",
                    source_url="https://www.sec.gov/example/filing",
                    amendment_type=None,
                    status=status,
                    reason="Synthetic failure" if status == "blocked" else None,
                    evidence={},
                )
            )
        session.commit()
    with database.connect() as connection:
        schema: str = connection.scalar(text("SELECT current_schema()"))
    environment: dict[str, str] = {
        **os.environ,
        "DATABASE_URL": database.url.render_as_string(hide_password=False),
        "PGOPTIONS": f"-csearch_path={schema}",
    }
    environment.pop("EDGAR_IDENTITY", None)
    result: subprocess.CompletedProcess[str] = subprocess.run(
        [
            sys.executable,
            "-m",
            "investor_platform.research_sync",
            "--quarters",
            "20",
            "--through-quarter",
            "2026-Q2",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    outcomes: list[dict] = [json.loads(line) for line in result.stdout.splitlines()]
    assert [row["manager"] for row in outcomes] == ["custom-alpha", "custom-beta"]
    assert all(row["status"] == "skipped" for row in outcomes)
    assert outcomes[0]["complete_filings"] == 2 and outcomes[0]["blocked_filings"] == 1
    assert outcomes[1]["complete_filings"] == outcomes[1]["blocked_filings"] == 0
    with Session(database) as session:
        assert session.scalar(select(func.count()).select_from(ResearchManager)) == 3
        assert session.scalar(select(func.count()).select_from(ResearchFiling)) == 5
        assert session.get(ResearchManager, alpha_id).profile == {"name": "Custom Alpha"}
