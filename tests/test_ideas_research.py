from datetime import date

import pytest

from harness.ideas.research import Match, validate_match


def match():
    return Match(
        accepted=True,
        reason="",
        fund="Alpha Fund",
        company="Acme",
        period="Q2 2026",
        period_end=date(2026, 6, 30),
        publisher_quote="Alpha Capital",
        fund_quote="Alpha Fund",
        company_quote="Acme pricing power",
        period_quote="Q2 2026",
    )


def test_match_requires_exact_identity_evidence():
    parts = [{"text": "Alpha Capital Alpha Fund Q2 2026 Acme pricing power"}]
    validate_match(match(), parts, date(2026, 9, 30))
    bad = match()
    bad.company_quote = "Acme doubled earnings"
    with pytest.raises(ValueError, match="verbatim"):
        validate_match(bad, parts, date(2026, 9, 30))


def test_rejects_future_stale_and_missing_periods():
    parts = [{"text": "Alpha Capital Alpha Fund Q2 2026 Acme pricing power"}]
    for period_end in [None, date(2027, 6, 30), date(2025, 6, 30)]:
        bad = match()
        bad.period_end = period_end
        with pytest.raises(ValueError):
            validate_match(bad, parts, date(2026, 9, 30))


def test_discovery_is_bounded_and_archives_rejections(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from uuid import uuid4

    from harness.ideas import research

    run_id = uuid4()
    run = {"id": run_id, "issue_date": date(2026, 9, 30)}
    row = {"ordinal": 1, "company": "Acme", "fund": "Alpha", "symbol": "ACM US"}
    monkeypatch.setattr(research.store, "get_run", lambda _: run)
    monkeypatch.setattr(research.store, "items", lambda _: [row])
    monkeypatch.setattr(research.store, "run_folder", lambda _: tmp_path)

    class Connection:
        def execute(self, *args):
            pass

    @contextmanager
    def connect():
        yield Connection()

    monkeypatch.setattr(research.store, "connect", connect)
    attempts = []

    def collector(folder, url):
        attempts.append(url)
        raise ValueError("Wrong fund")

    searcher = lambda _: (
        [{"url": "https://hfbestideas.com/stock/ACM"}]
        + [{"url": f"https://manager.com/{i}"} for i in range(6)]
    )
    result = research.discover(run_id, 1, searcher=searcher, collector=collector)
    assert len(attempts) == 6
    assert all("hfbestideas" not in url for url in attempts)
    assert "gap" in result
    assert len(list((tmp_path / "research/searches").glob("*.json"))) == 1


def test_archive_page_exposes_original_pdf_links(tmp_path):
    from harness.ideas.research import linked_letters

    path = tmp_path / "research/documents/a.html"
    path.parent.mkdir(parents=True)
    path.write_text(
        '<a href="/letters/2026-q2.pdf">Q2 2026</a><a href="/letters/2025-q4.pdf">2025</a>'
    )
    assert linked_letters(
        tmp_path, {"sha256": "a", "url": "https://manager.com/letters"}, 2026
    ) == ["https://manager.com/letters/2026-q2.pdf"]


def test_provider_schema_avoids_unsupported_additional_properties():
    import json

    from harness.ideas.model import provider_schema

    assert "additionalProperties" not in json.dumps(provider_schema(Match))


def test_archive_links_ignore_regulatory_footer_and_fact_sheets(tmp_path):
    from harness.ideas.research import linked_letters

    path = tmp_path / "research/documents/a.html"
    path.parent.mkdir(parents=True)
    path.write_text(
        '<article><a href="/2026/q2-commentary.pdf">Q2 Commentary</a><a href="/2026/q2-fact-sheet.pdf">Q2 fact sheet</a></article><footer><a href="/2026/crs-fund.pdf">CRS</a></footer>'
    )
    assert linked_letters(
        tmp_path, {"sha256": "a", "url": "https://manager.com/letter"}, 2026
    ) == ["https://manager.com/2026/q2-commentary.pdf"]


def test_identity_checks_tolerate_pdf_line_breaks_and_capitals():
    m = match()
    m.fund_quote = "ALPHA\nFUND"
    m.company_quote = "ACME pricing power"
    m.publisher_quote = "ALPHA CAPITAL"
    validate_match(
        m,
        [{"text": "Alpha Capital Alpha Fund Q2 2026 Acme pricing power"}],
        date(2026, 9, 30),
    )


def test_company_and_sibling_fund_cannot_be_substituted():
    from harness.ideas.research import validate_target

    m = match()
    with pytest.raises(ValueError, match="company"):
        validate_target(
            m, {"company": "Samsung", "fund": "Alpha Fund", "symbol": "SSNLF US"}
        )
    with pytest.raises(ValueError, match="fund"):
        validate_target(
            m, {"company": "Acme", "fund": "Alpha Global Fund", "symbol": "ACM US"}
        )
    validate_target(
        m, {"company": "Acme Corporation", "fund": "Alpha Strategy", "symbol": "ACM US"}
    )
