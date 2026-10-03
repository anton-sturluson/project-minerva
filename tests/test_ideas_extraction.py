import pytest

from harness.ideas.extraction import (
    Claim,
    Review,
    View,
    materialize,
    passages,
    validate_review,
)


def view(text="Acme has pricing power."):
    return View(
        instrument="equity",
        stance="bull",
        action="not stated",
        claims=[Claim(text=text, passages=["p1.1"])],
        gap="",
    )


def test_model_selects_ids_and_cannot_invent_quotes():
    spans = passages(
        [{"id": "p1", "text": "Acme has pricing power.\n\nNext paragraph."}]
    )
    result = materialize(view(), spans)
    assert result["claims"][0]["evidence"] == [
        {"block": "p1.1", "quote": "Acme has pricing power."}
    ]
    with pytest.raises(ValueError, match="unknown"):
        materialize(view(), {"p2.1": "Acme has pricing power."})


def test_invented_number_fails_even_with_authentic_passage():
    with pytest.raises(ValueError, match="number"):
        materialize(view("Acme will grow 500%."), {"p1.1": "Acme has pricing power."})


def test_semantic_rejection_blocks_authentic_evidence_with_false_claim():
    v = view("The manager guarantees shares will triple next week.")
    materialize(v, {"p1.1": "Acme has pricing power."})
    r = Review(
        matching_fund_company_period=True,
        investment_reasoning_supported=True,
        stance_and_action_supported=True,
        claims_supported=[False],
        reason="Guarantee is absent from source",
    )
    with pytest.raises(ValueError, match="Guarantee"):
        validate_review(v, r)
    r.claims_supported = []
    with pytest.raises(ValueError):
        validate_review(v, r)


def test_extraction_routes_source_and_claims_to_separate_models(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from datetime import date
    from uuid import uuid4

    from harness.ideas import extraction

    calls = []
    run_id = uuid4()
    row = {
        "ordinal": 1,
        "company": "Acme",
        "fund": "Alpha",
        "document": {"url": "https://example.com/letter"},
    }
    monkeypatch.setattr(
        extraction.store, "get_run", lambda _: {"issue_date": date(2026, 9, 30)}
    )
    monkeypatch.setattr(extraction.store, "items", lambda _: [row])
    monkeypatch.setattr(extraction.store, "run_folder", lambda _: tmp_path)

    @contextmanager
    def connect():
        class Connection:
            def execute(self, *args):
                pass

        yield Connection()

    monkeypatch.setattr(extraction.store, "connect", connect)

    class Identity:
        def model_dump(self, **kw):
            return {"period": "Q2 2026"}

    monkeypatch.setattr(
        extraction,
        "assess",
        lambda *a, model: calls.append(("source", model)) or Identity(),
    )
    monkeypatch.setattr(extraction, "resolve_identity", lambda *a: {})
    monkeypatch.setattr(extraction, "validate_match", lambda *a: None)
    monkeypatch.setattr(
        extraction,
        "load_sections",
        lambda *a: [{"id": "p1", "text": "Acme has pricing power."}],
    )

    def generate(prompt, schema, folder, *, model):
        calls.append((schema.__name__, model))
        if schema is View:
            return view()
        return Review(
            matching_fund_company_period=True,
            investment_reasoning_supported=True,
            stance_and_action_supported=True,
            claims_supported=[True],
            reason="Supported",
        )

    monkeypatch.setattr(extraction, "generate", generate)
    for stage in ("SOURCE", "EXTRACTION", "REVIEW"):
        monkeypatch.delenv(f"MINERVA_IDEAS_{stage}_MODEL", raising=False)
    extraction.extract(run_id, 1)
    assert calls == [
        ("source", "gpt-6-luna"),
        ("View", "gpt-6.1-sol"),
        ("Review", "gpt-6.1-sol"),
    ]
