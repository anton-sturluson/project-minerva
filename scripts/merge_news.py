#!/usr/bin/env python3
"""Merge raw news markdown files into articles.md, INDEX.md, and update LEDGER.md.

Usage:
    python merge_news.py --raw-dir <path> --articles <path> --index <path> --ledger <path> --date <YYYY-MM-DD>
"""

from __future__ import annotations

import argparse
import re
from datetime import datetime, timezone
from pathlib import Path


def parse_raw_file(path: Path) -> dict:
    """Parse a raw news markdown file and extract metadata + article count."""
    text = path.read_text(encoding="utf-8")
    lines = text.strip().splitlines()

    # Extract source name from H1: "# WSJ — 2026-05-03"
    source_name = ""
    if lines and lines[0].startswith("# "):
        h1 = lines[0].lstrip("# ").strip()
        # Strip date suffix: "WSJ — 2026-05-03" → "WSJ"
        source_name = re.split(r"\s*[—–-]\s*\d{4}-\d{2}-\d{2}", h1)[0].strip()

    # Extract status from metadata block
    status = "ok"
    for line in lines[1:10]:  # metadata is in first few lines
        if line.lower().startswith("status:"):
            status = line.split(":", 1)[1].strip().lower()
            break

    # Count articles: each ## heading is an article
    article_count = sum(1 for line in lines if line.startswith("## "))

    return {
        "filename": path.name,
        "source_name": source_name or path.stem,
        "status": status,
        "article_count": article_count,
        "text": text,
    }


def build_articles_md(date: str, sources: list[dict]) -> str:
    """Build the merged articles.md content."""
    ok = sum(1 for s in sources if s["status"] == "ok")
    degraded = sum(1 for s in sources if s["status"] == "degraded")
    failed = sum(1 for s in sources if s["status"] == "failed")
    total_articles = sum(s["article_count"] for s in sources)

    lines = [
        f"# News Collection — {date}",
        "",
        f"Sources: {ok} ok · {degraded} degraded · {failed} failed",
        f"Total articles: {total_articles}",
        "",
    ]

    for source in sources:
        lines.append("---")
        lines.append("")
        lines.append(source["text"].strip())
        lines.append("")

    return "\n".join(lines) + "\n"


def build_index_md(date: str, sources: list[dict]) -> str:
    """Build the daily INDEX.md summary table."""
    lines = [
        f"# {date}",
        "",
        f"News collection for {date}.",
        "",
        "| Source | Status | Articles | Raw file |",
        "| --- | --- | --- | --- |",
    ]

    for source in sources:
        name = source["source_name"]
        status = source["status"]
        count = source["article_count"]
        filename = source["filename"]
        lines.append(f"| {name} | {status} | {count} | [{filename}](./raw/{filename}) |")

    lines.append("")
    lines.append("Merged output: [articles.md](./articles.md)")
    lines.append("")

    return "\n".join(lines) + "\n"


def update_ledger(ledger_path: Path, date: str, sources: list[dict]) -> None:
    """Append a row to LEDGER.md if the date doesn't already have one."""
    ledger_text = ledger_path.read_text(encoding="utf-8") if ledger_path.exists() else ""

    # Idempotent: skip if date row exists
    if f"| {date} |" in ledger_text:
        return

    ok = sum(1 for s in sources if s["status"] == "ok")
    degraded = sum(1 for s in sources if s["status"] == "degraded")
    failed = sum(1 for s in sources if s["status"] == "failed")
    total_articles = sum(s["article_count"] for s in sources)

    ok_str = str(ok)
    degraded_str = str(degraded) if degraded > 0 else "0"
    if failed > 0:
        degraded_str += f" ({failed} failed)"

    row = f"| {date} | {ok_str} | {degraded_str} | {total_articles} | |"

    # Append row
    if not ledger_text.endswith("\n"):
        ledger_text += "\n"
    ledger_text += row + "\n"
    ledger_path.write_text(ledger_text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge raw news markdown files")
    parser.add_argument("--raw-dir", required=True, help="Directory containing raw/*.md files")
    parser.add_argument("--articles", required=True, help="Output path for articles.md")
    parser.add_argument("--index", required=True, help="Output path for INDEX.md")
    parser.add_argument("--ledger", required=True, help="Path to LEDGER.md")
    parser.add_argument("--date", required=True, help="Collection date (YYYY-MM-DD)")
    args = parser.parse_args()

    raw_dir = Path(args.raw_dir)
    if not raw_dir.exists():
        print(f"raw directory does not exist: {raw_dir}")
        raise SystemExit(1)

    # Read and parse all raw markdown files
    raw_files = sorted(raw_dir.glob("*.md"))
    if not raw_files:
        print(f"no raw .md files found in {raw_dir}")
        raise SystemExit(1)

    sources = [parse_raw_file(f) for f in raw_files]

    # Sort: editorial sources first, then IR sources
    def sort_key(s: dict) -> tuple:
        is_ir = s["filename"].startswith("ir-")
        return (is_ir, s["source_name"].lower())

    sources.sort(key=sort_key)

    # Write articles.md
    articles_path = Path(args.articles)
    articles_path.write_text(build_articles_md(args.date, sources), encoding="utf-8")
    print(f"articles: {articles_path} ({len(sources)} sources, {sum(s['article_count'] for s in sources)} articles)")

    # Write INDEX.md
    index_path = Path(args.index)
    index_path.write_text(build_index_md(args.date, sources), encoding="utf-8")
    print(f"index: {index_path}")

    # Update LEDGER.md
    ledger_path = Path(args.ledger)
    update_ledger(ledger_path, args.date, sources)
    print(f"ledger: {ledger_path}")


if __name__ == "__main__":
    main()
