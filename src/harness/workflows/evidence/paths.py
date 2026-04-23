"""Path helpers for the evidence and analysis workflow tree."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True, frozen=True)
class CompanyPaths:
    """Deterministic paths inside a company evidence root."""

    root: Path

    @property
    def notes_dir(self) -> Path:
        return self.root / "notes"

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def sources_dir(self) -> Path:
        return self.data_dir / "sources"

    @property
    def references_dir(self) -> Path:
        return self.data_dir / "references"

    @property
    def reference_dir(self) -> Path:
        return self.references_dir

    @property
    def structured_dir(self) -> Path:
        return self.data_dir / "structured"

    @property
    def meta_dir(self) -> Path:
        return self.data_dir / "meta"

    @property
    def structured_meta_dir(self) -> Path:
        return self.meta_dir

    @property
    def extraction_runs_dir(self) -> Path:
        return self.meta_dir / "extraction-runs"

    @property
    def research_dir(self) -> Path:
        return self.root / "research"

    @property
    def analysis_dir(self) -> Path:
        return self.root / "analysis"

    @property
    def analysis_meta_dir(self) -> Path:
        return self.analysis_dir

    @property
    def context_dir(self) -> Path:
        return self.analysis_dir

    @property
    def bundles_dir(self) -> Path:
        return self.analysis_dir / "bundles"

    @property
    def provenance_dir(self) -> Path:
        return self.root / "provenance"

    @property
    def source_registry_json(self) -> Path:
        return self.meta_dir / "source-registry.json"

    @property
    def source_registry_md(self) -> Path:
        return self.meta_dir / "source-registry.md"

    @property
    def inventory_json(self) -> Path:
        return self.meta_dir / "inventory.json"

    @property
    def inventory_md(self) -> Path:
        return self.meta_dir / "inventory.md"

    @property
    def coverage_json(self) -> Path:
        return self.meta_dir / "coverage.json"

    @property
    def coverage_md(self) -> Path:
        return self.meta_dir / "coverage.md"

    @property
    def sec_collection_summary_json(self) -> Path:
        return self.meta_dir / "sec-collection-summary.json"

    @property
    def sec_collection_summary_md(self) -> Path:
        return self.meta_dir / "sec-collection-summary.md"

    @property
    def evidence_jsonl(self) -> Path:
        return self.data_dir / "evidence.jsonl"

    @property
    def evidence_md(self) -> Path:
        return self.data_dir / "evidence.md"

    @property
    def audits_dir(self) -> Path:
        return self.root / "audits"

    @property
    def plans_dir(self) -> Path:
        return self.root / "plans"

    @property
    def ledger_md(self) -> Path:
        return self.root / "LEDGER.md"

    @property
    def status_json(self) -> Path:
        return self.analysis_dir / "status.json"

    @property
    def status_md(self) -> Path:
        return self.analysis_dir / "status.md"

    @property
    def context_manifest_json(self) -> Path:
        return self.analysis_dir / "context-manifest.json"

    @property
    def context_manifest_md(self) -> Path:
        return self.analysis_dir / "context-manifest.md"


def resolve_company_root(raw_root: str | Path) -> CompanyPaths:
    """Resolve a raw root path to an absolute company path bundle."""
    candidate = Path(raw_root).expanduser()
    if not candidate.is_absolute():
        candidate = (Path.cwd() / candidate).resolve()
    return CompanyPaths(root=candidate.resolve())
