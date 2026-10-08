"""Verify historical collection counts include saved filings, amendments and new imports."""

from datetime import date
from uuid import UUID

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from investor_platform.db import LOCAL_WORKSPACE
from investor_platform.models import ResearchFiling, ResearchManager
from investor_platform.research_sync import filing_counts


def add_filing(
    session: Session,
    manager_id: UUID,
    accession: str,
    period: str,
    status: str,
    *,
    amended: bool = False,
) -> None:
    """Store a synthetic original or amendment with its validation result."""
    session.add(
        ResearchFiling(
            manager_id=manager_id,
            accession=accession,
            report_period=date.fromisoformat(period),
            filed_date=date(2026, 8, 1),
            form="13F-HR/A" if amended else "13F-HR",
            source_url="https://www.sec.gov/example/filing",
            amendment_type="RESTATEMENT" if amended else None,
            status=status,
            reason="Synthetic validation failure" if status == "blocked" else None,
            evidence={},
        )
    )
    session.flush()


def test_counts_cover_report_scope_saved_and_new_filings(database: Engine) -> None:
    """Counts distinguish validation results without conflating amendments with usable quarters."""
    with Session(database) as session:
        manager: ResearchManager = ResearchManager(
            workspace_id=LOCAL_WORKSPACE,
            slug="example",
            cik="1001",
            profile={"name": "Example"},
        )
        other: ResearchManager = ResearchManager(
            workspace_id=LOCAL_WORKSPACE,
            slug="other",
            cik="1002",
            profile={"name": "Other"},
        )
        session.add_all([manager, other])
        session.flush()
        add_filing(session, manager.id, "older", "2015-12-31", "complete")
        add_filing(session, manager.id, "first", "2016-03-31", "complete")
        add_filing(session, manager.id, "blocked", "2016-06-30", "blocked")
        add_filing(session, manager.id, "amendment", "2016-06-30", "complete", amended=True)
        add_filing(session, other.id, "foreign", "2026-06-30", "complete")
        session.commit()
        assert filing_counts(session, manager.id, 2016) == {
            "complete_filings": 2,
            "blocked_filings": 1,
        }
        add_filing(session, manager.id, "new", "2026-03-31", "complete")
        add_filing(session, manager.id, "new-blocked", "2026-06-30", "blocked", amended=True)
        session.commit()
        assert filing_counts(session, manager.id, 2016) == {
            "complete_filings": 3,
            "blocked_filings": 2,
        }
        assert filing_counts(session, manager.id, 2026) == {
            "complete_filings": 1,
            "blocked_filings": 1,
        }
        assert filing_counts(session, manager.id, 2027) == {
            "complete_filings": 0,
            "blocked_filings": 0,
        }
        assert filing_counts(session, other.id, 2016) == {
            "complete_filings": 1,
            "blocked_filings": 0,
        }
