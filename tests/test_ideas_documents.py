import pytest

from harness.ideas.documents import archive, load_sections, public_url


def test_archive_hashes_bytes_and_preserves_locations(tmp_path):
    payload = b"<html><article><h1>Alpha Fund Q2 2026</h1><p>Acme pricing power supports cash generation. This is substantive company commentary with enough readable text for the source archive.</p></article></html>"
    fetch = lambda url: (payload, url)
    a = archive(tmp_path, "https://manager.com/letter", fetch=fetch)
    b = archive(tmp_path, "https://manager.com/other-link", fetch=fetch)
    assert a["sha256"] == b["sha256"]
    assert len(list((tmp_path / "research/documents").glob("*.html"))) == 1
    assert load_sections(tmp_path, a)[1]["id"] == "b2"
    assert "Acme" in load_sections(tmp_path, a)[1]["text"]


@pytest.mark.parametrize(
    "url",
    [
        "http://manager.com/letter",
        "https://hfbestideas.com/stock/A",
        "https://hfbestideas.substack.com/p/a",
        "https://user:password@manager.com/a",
        "https://127.0.0.1/a",
    ],
)
def test_rejects_aggregator_and_nonpublic_sources(url):
    with pytest.raises(ValueError):
        public_url(url)
