"""Crawl orchestrator: ATS fetch -> diff -> classify -> store."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import traceback
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from jobwatch.ats.ashby import AshbyClient
from jobwatch.ats.ashby_ssr import AshbySSRClient
from jobwatch.ats.base import ATSClient
from jobwatch.ats.greenhouse import GreenhouseClient
from jobwatch.classifier import AnthropicClassifier, ClassifierProvider, OpenAIClassifier
from jobwatch.config import COMPANY_REGISTRY, CompanyConfig, Settings
from jobwatch.db import JobWatchDB
from jobwatch.models import (
    ATSType,
    CrawlStatus,
    FetchResult,
    JobClassification,
    ReclassifyTrigger,
)

logger: logging.Logger = logging.getLogger(__name__)

_ATS_CLIENT_MAP: dict[ATSType, type[ATSClient]] = {
    ATSType.GREENHOUSE: GreenhouseClient,
    ATSType.ASHBY: AshbyClient,
    ATSType.ASHBY_SSR: AshbySSRClient,
}


def get_ats_client(company: CompanyConfig) -> ATSClient:
    """Return the ATS client for a company's configured ATS type."""
    client_cls: type[ATSClient] | None = _ATS_CLIENT_MAP.get(company.ats_type)
    if client_cls is None:
        raise ValueError(f"Unknown ATS type: {company.ats_type}")
    return client_cls(company.ats_board)


def compute_content_hash(title: str, description: str | None) -> str:
    """SHA-256 hex digest of title + description."""
    payload: str = title + (description or "")
    return hashlib.sha256(payload.encode()).hexdigest()


def crawl_company(
    db: JobWatchDB,
    company: CompanyConfig,
    classifier: ClassifierProvider,
    settings: Settings,
) -> dict:
    """Crawl a single company: fetch, diff, classify, store.

    Returns a summary dict with counts for new, changed, closed, unchanged postings.
    """
    now: str = datetime.now(timezone.utc).isoformat()
    crawl_date: str = now[:10]

    db.ensure_company(
        company.id, company.name, company.ats_type, company.ats_board, company.website
    )
    run_id: int = db.create_crawl_run(company.id, now)

    try:
        client: ATSClient = get_ats_client(company)
        result: FetchResult = client.fetch_all()
        logger.info(
            "%s: fetched %d postings (exhaustive=%s)",
            company.id, len(result.postings), result.is_exhaustive,
        )

        existing: dict[str, dict] = db.get_active_postings(company.id)

        new_count: int = 0
        changed_count: int = 0
        unchanged_count: int = 0
        classified_count: int = 0
        seen_ids: set[str] = set()

        for raw in result.postings:
            posting_id: str = f"{company.id}:{raw.ats_job_id}"
            content_hash: str = compute_content_hash(raw.title, raw.description)
            seen_ids.add(posting_id)

            posting_dict: dict = raw.model_dump()
            pid: str
            is_new: bool
            content_changed: bool
            pid, is_new, content_changed = db.upsert_posting(
                company.id, posting_dict, content_hash, crawl_date
            )

            if is_new:
                new_count += 1
            elif content_changed:
                changed_count += 1
            else:
                unchanged_count += 1

            if is_new or content_changed:
                already_classified: bool = db.has_current_classification(
                    pid, content_hash, settings.taxonomy_version, settings.prompt_version
                )
                if not already_classified:
                    classification: JobClassification = classifier.classify(
                        raw.title, raw.department_raw, raw.description
                    )
                    trigger: str = (
                        ReclassifyTrigger.NEW_POSTING if is_new
                        else ReclassifyTrigger.CONTENT_CHANGE
                    )
                    db.insert_classification(
                        pid,
                        classification.model_dump(),
                        classifier.model_name,
                        settings.taxonomy_version,
                        settings.prompt_version,
                        trigger,
                    )
                    classified_count += 1

        closed_count: int = 0
        if result.is_exhaustive:
            missing_ids: set[str] = set(existing.keys()) - seen_ids
            for mid in missing_ids:
                db.close_posting(mid, now)
                closed_count += 1
            if missing_ids:
                logger.info("%s: closed %d postings", company.id, closed_count)

            # Materialize snapshot from current DB state
            active_rows: list[dict] = db.get_all_active_postings_with_classifications(
                company.id
            )
            dept_counter: Counter[str] = Counter()
            role_counter: Counter[str] = Counter()
            seniority_counter: Counter[str] = Counter()
            for row in active_rows:
                dept_counter[row.get("department") or "UNKNOWN"] += 1
                role_counter[row.get("role_type") or "UNKNOWN.GEN"] += 1
                seniority_counter[row.get("seniority") or "UNKNOWN"] += 1

            db.insert_snapshot(
                company_id=company.id,
                crawl_run_id=run_id,
                crawl_date=crawl_date,
                total_active=len(active_rows),
                dept_counts=dict(dept_counter),
                role_type_counts=dict(role_counter),
                seniority_counts=dict(seniority_counter),
                new_postings=new_count,
                closed_postings=closed_count,
            )

        db.update_crawl_run(
            run_id,
            status=CrawlStatus.COMPLETE,
            is_exhaustive=result.is_exhaustive,
            postings_found=len(result.postings),
            postings_new=new_count,
            postings_closed=closed_count,
            postings_changed=changed_count,
            response_hash=result.response_hash,
            finished_at=datetime.now(timezone.utc).isoformat(),
        )

        summary: dict = {
            "company_id": company.id,
            "status": CrawlStatus.COMPLETE,
            "postings_found": len(result.postings),
            "new": new_count,
            "changed": changed_count,
            "unchanged": unchanged_count,
            "closed": closed_count,
            "classified": classified_count,
        }
        logger.info("%s: crawl complete — %s", company.id, summary)
        return summary

    except Exception:
        db.update_crawl_run(
            run_id,
            status=CrawlStatus.FAILED,
            error_message=traceback.format_exc(),
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
        raise


def crawl_all(
    db: JobWatchDB,
    classifier: ClassifierProvider,
    settings: Settings,
    company_ids: list[str] | None = None,
) -> list[dict]:
    """Crawl companies serially (v1). Returns list of per-company result dicts."""
    if company_ids is not None:
        id_set: set[str] = set(company_ids)
        companies: list[CompanyConfig] = [
            c for c in COMPANY_REGISTRY if c.id in id_set
        ]
    else:
        companies = list(COMPANY_REGISTRY)

    results: list[dict] = []
    for company in companies:
        try:
            result: dict = crawl_company(db, company, classifier, settings)
            results.append(result)
        except Exception:
            logger.exception("Failed to crawl %s", company.id)
            results.append({
                "company_id": company.id,
                "status": CrawlStatus.FAILED,
            })

    total_found: int = sum(r.get("postings_found", 0) for r in results)
    total_new: int = sum(r.get("new", 0) for r in results)
    total_closed: int = sum(r.get("closed", 0) for r in results)
    logger.info(
        "Crawl complete: %d companies, %d postings found, %d new, %d closed",
        len(results), total_found, total_new, total_closed,
    )
    return results


def main():
    """CLI entry point for the crawl orchestrator."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="JobWatch crawl orchestrator"
    )
    parser.add_argument(
        "--companies", type=str, default=None,
        help="Comma-separated company ids to crawl (default: all)",
    )
    parser.add_argument(
        "--db-path", type=str, default="data/jobwatch.db",
        help="Path to SQLite database (default: data/jobwatch.db)",
    )
    parser.add_argument(
        "--classifier", type=str, default="anthropic",
        choices=["anthropic", "openai"],
        help="LLM classifier provider (default: anthropic)",
    )
    parser.add_argument(
        "--model", type=str, default=None,
        help="Override model name for the classifier",
    )
    args: argparse.Namespace = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    company_ids: list[str] | None = (
        [cid.strip() for cid in args.companies.split(",")]
        if args.companies else None
    )

    settings: Settings = Settings(db_path=Path(args.db_path))

    classifier_kwargs: dict = {}
    if args.model:
        classifier_kwargs["model"] = args.model

    classifier: ClassifierProvider
    if args.classifier == "anthropic":
        classifier = AnthropicClassifier(**classifier_kwargs)
    else:
        classifier = OpenAIClassifier(**classifier_kwargs)

    db: JobWatchDB = JobWatchDB(settings.db_path)
    db.init_db()

    try:
        results: list[dict] = crawl_all(db, classifier, settings, company_ids)
        print(json.dumps(results, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
