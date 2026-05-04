#!/usr/bin/env python3
"""Merge raw news articles and their summaries into per-source summaries,
articles.md, INDEX.md, and update LEDGER.md.

Usage:
    python merge_news.py --raw-dir <path> --summaries-dir <path> --date-dir <path> --ledger <path> --date <YYYY-MM-DD>
"""

from __future__ import annotations

import argparse
import re
from collections import defaultdict
from pathlib import Path


def parse_raw_header(path: Path) -> dict:
    """Parse metadata from a raw article's markdown header."""
    text = path.read_text(encoding="utf-8")
    lines = text.strip().splitlines()

    headline = ""
    if lines and lines[0].startswith("# "):
        headline = lines[0].lstrip("# ").strip()

    meta: dict[str, str] = {}
    for line in lines[1:15]:
        if ":" in line and not line.startswith("#"):
            key, _, val = line.partition(":")
            key = key.strip().lower()
            if key in ("source", "url", "published", "collected", "section"):
                meta[key] = val.strip()
        elif line.startswith("#") or (line.strip() and ":" not in line):
            break

    return {
        "filename": path.name,
        "headline": headline,
        "source_name": meta.get("source", ""),
        "url": meta.get("url", ""),
        "published": meta.get("published", ""),
        "collected": meta.get("collected", ""),
        "section": meta.get("section", ""),
    }


def extract_source_prefix(filename: str) -> str:
    """Extract the source prefix from a filename like 'wsj-trump-hormuz.md' → 'wsj'
    or 'ir-GOOGL-q1-results.md' → 'ir-GOOGL'."""
    stem = filename.rsplit(".", 1)[0]  # remove .md
    parts = stem.split("-")

    # IR files: ir-TICKER-slug → prefix is ir-TICKER
    if parts[0] == "ir" and len(parts) >= 3:
        return f"{parts[0]}-{parts[1]}"

    # Editorial files: source-slug → prefix is first part
    return parts[0]


def source_display_name(prefix: str) -> str:
    """Convert prefix to display name."""
    names = {
        "wsj": "Wall Street Journal",
        "economist": "The Economist",
        "reuters-markets": "Reuters Markets",
        "bls-calendar": "BLS Release Calendar",
        "bea-schedule": "BEA Release Schedule",
        "fed-press": "Federal Reserve",
    }
    if prefix.startswith("ir-"):
        ticker = prefix.split("-", 1)[1]
        return f"IR — {ticker}"
    return names.get(prefix, prefix)


def build_source_summary(
    prefix: str, display_name: str, articles: list[dict], summaries_dir: Path
) -> str:
    """Build a per-source summary markdown string."""
    lines = [
        f"# {display_name}",
        "",
        f"Articles: {len(articles)}",
        "",
    ]

    for art in articles:
        lines.append(f"## {art['headline']}")
        meta_parts = []
        if art["section"]:
            meta_parts.append(f"Section: {art['section']}")
        if art["published"]:
            meta_parts.append(f"Published: {art['published']}")
        meta_parts.append(f"[full article](./raw/{art['filename']})")
        if art["url"]:
            meta_parts.append(f"[source]({art['url']})")
        lines.append(" | ".join(meta_parts))
        lines.append("")

        # Read the extract-files summary if it exists
        summary_file = summaries_dir / art["filename"]
        if summary_file.exists():
            summary_text = summary_file.read_text(encoding="utf-8").strip()
            lines.append(summary_text)
        else:
            lines.append("*Summary not available.*")

        lines.append("")

    return "\n".join(lines)


def build_articles_md(date: str, source_summaries: list[tuple[str, str]]) -> str:
    """Build articles.md from per-source summary content."""
    total_articles = 0
    for _, content in source_summaries:
        total_articles += content.count("\n## ") + (1 if content.startswith("# ") else 0)
        # Actually count ## headings properly
    # Recount
    total_articles = sum(
        content.count("\n## ") for _, content in source_summaries
    )

    lines = [
        f"# News Collection — {date}",
        "",
        f"Sources: {len(source_summaries)} | Articles: {total_articles}",
        "",
    ]

    for _, content in source_summaries:
        lines.append("---")
        lines.append("")
        lines.append(content.strip())
        lines.append("")

    return "\n".join(lines) + "\n"


def build_index_md(date: str, raw_files: list[dict], source_groups: dict) -> str:
    """Build INDEX.md with source table and raw file listing."""
    lines = [
        f"# {date}",
        "",
        f"News collection for {date}.",
        "",
        "## Sources",
        "",
        "| Source | Articles | Summary |",
        "| --- | --- | --- |",
    ]

    for prefix in sorted(source_groups.keys()):
        display = source_display_name(prefix)
        count = len(source_groups[prefix])
        lines.append(
            f"| {display} | {count} | [{prefix}-summary.md](./{prefix}-summary.md) |"
        )

    lines.extend(["", "## Raw articles", ""])
    for art in sorted(raw_files, key=lambda a: a["filename"]):
        lines.append(f"- [{art['headline']}](./raw/{art['filename']})")

    lines.extend(
        ["", "Merged summaries: [articles.md](./articles.md)", ""]
    )

    return "\n".join(lines) + "\n"


def update_ledger(ledger_path: Path, date: str, source_count: int, article_count: int) -> None:
    """Append a row to LEDGER.md if the date doesn't already have one."""
    ledger_text = ledger_path.read_text(encoding="utf-8") if ledger_path.exists() else ""

    if f"| {date} |" in ledger_text:
        # Update existing row
        new_lines = []
        for line in ledger_text.splitlines():
            if line.startswith(f"| {date} |"):
                line = f"| {date} | {source_count} | {article_count} | |"
            new_lines.append(line)
        ledger_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        return

    if not ledger_text.endswith("\n"):
        ledger_text += "\n"
    ledger_text += f"| {date} | {source_count} | {article_count} | |\n"
    ledger_path.write_text(ledger_text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge news summaries")
    parser.add_argument("--raw-dir", required=True, help="Directory containing raw article .md files")
    parser.add_argument("--summaries-dir", required=True, help="Directory containing extract-files summary .md files")
    parser.add_argument("--date-dir", required=True, help="Date directory for output (per-source summaries, articles.md, INDEX.md)")
    parser.add_argument("--ledger", required=True, help="Path to LEDGER.md")
    parser.add_argument("--date", required=True, help="Collection date (YYYY-MM-DD)")
    args = parser.parse_args()

    raw_dir = Path(args.raw_dir)
    summaries_dir = Path(args.summaries_dir)
    date_dir = Path(args.date_dir)

    if not raw_dir.exists():
        print(f"raw directory does not exist: {raw_dir}")
        raise SystemExit(1)

    # Read all raw article files
    raw_files = sorted(raw_dir.glob("*.md"))
    error_files = [f for f in raw_files if f.name.endswith("-error.md")]
    article_files = [f for f in raw_files if not f.name.endswith("-error.md")]

    if not article_files:
        print(f"no raw article files found in {raw_dir}")
        raise SystemExit(1)

    # Parse headers from all raw articles
    articles = [parse_raw_header(f) for f in article_files]

    # Group by source prefix
    source_groups: dict[str, list[dict]] = defaultdict(list)
    for art in articles:
        prefix = extract_source_prefix(art["filename"])
        source_groups[prefix].append(art)

    # Build per-source summary files
    source_summaries: list[tuple[str, str]] = []
    for prefix in sorted(source_groups.keys()):
        display = source_display_name(prefix)
        content = build_source_summary(prefix, display, source_groups[prefix], summaries_dir)

        # Write per-source summary
        summary_path = date_dir / f"{prefix}-summary.md"
        summary_path.write_text(content, encoding="utf-8")

        source_summaries.append((prefix, content))

    print(f"source summaries: {len(source_summaries)} files")

    # Build articles.md
    articles_path = date_dir / "articles.md"
    articles_path.write_text(
        build_articles_md(args.date, source_summaries), encoding="utf-8"
    )
    print(f"articles: {articles_path} ({len(articles)} articles)")

    # Build INDEX.md
    index_path = date_dir / "INDEX.md"
    index_path.write_text(
        build_index_md(args.date, articles, source_groups), encoding="utf-8"
    )
    print(f"index: {index_path}")

    # Update LEDGER.md
    ledger_path = Path(args.ledger)
    update_ledger(ledger_path, args.date, len(source_groups), len(articles))
    print(f"ledger: {ledger_path}")


if __name__ == "__main__":
    main()
