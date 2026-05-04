#!/usr/bin/env python3
"""Flatten ticker-nested source directories in company evidence trees.

Scans hard-disk/reports/00-companies/*/data/sources/ for ticker folders
(e.g. RDDT/, TEAM/) and merges their children into the parent sources/ dir.

Usage:
    python3 scripts/fix_ticker_nesting.py              # dry-run (default)
    python3 scripts/fix_ticker_nesting.py --execute     # actually move files
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

REAL_SOURCE_TYPES = {
    "10-K", "10-Q", "8-K", "earnings", "financials", "proxy", "news",
    "competitors", "transcripts", "presentations", "references",
    "investor-materials", "partnership", "legacy", "sec", "web", "assets",
    "webcasts",
}

BASE = Path(__file__).resolve().parent.parent / "hard-disk" / "reports" / "00-companies"


def find_ticker_dirs() -> list[dict]:
    """Find all ticker-nested directories that need flattening."""
    results = []
    for company_dir in sorted(BASE.iterdir()):
        sources = company_dir / "data" / "sources"
        if not sources.exists():
            continue
        for d in sorted(sources.iterdir()):
            if not d.is_dir() or d.name in REAL_SOURCE_TYPES or d.name.startswith(".") or d.name == "INDEX.md":
                continue
            children = [c for c in d.iterdir() if c.is_dir() and c.name in REAL_SOURCE_TYPES]
            if not children:
                continue
            results.append({
                "company": company_dir.name,
                "sources_dir": sources,
                "ticker_dir": d,
                "ticker": d.name,
                "children": sorted(c.name for c in children),
            })
    return results


def check_conflicts(ticker_dir: Path, sources_dir: Path) -> list[dict]:
    """Check for file-level conflicts between nested and flat directories."""
    conflicts = []
    for nested_file in ticker_dir.rglob("*"):
        if not nested_file.is_file():
            continue
        rel = nested_file.relative_to(ticker_dir)
        flat_target = sources_dir / rel
        if flat_target.exists():
            h1 = hashlib.md5(nested_file.read_bytes()).hexdigest()
            h2 = hashlib.md5(flat_target.read_bytes()).hexdigest()
            conflicts.append({
                "nested": nested_file,
                "flat": flat_target,
                "rel": rel,
                "same_hash": h1 == h2,
            })
    return conflicts


def flatten_one(ticker_dir: Path, sources_dir: Path, *, execute: bool) -> list[str]:
    """Flatten one ticker directory into its parent sources dir."""
    log = []
    for child in sorted(ticker_dir.iterdir()):
        if not child.is_dir():
            # Stray files at ticker level — move them too
            target = sources_dir / child.name
            if target.exists():
                log.append(f"  SKIP (exists): {child.name}")
                continue
            log.append(f"  MOVE file: {child.name}")
            if execute:
                shutil.move(str(child), str(target))
            continue

        target = sources_dir / child.name
        if target.exists():
            # Merge: move files from nested into existing flat dir
            for nested_file in sorted(child.rglob("*")):
                if not nested_file.is_file():
                    continue
                rel = nested_file.relative_to(child)
                flat_target = target / rel
                if flat_target.exists():
                    h1 = hashlib.md5(nested_file.read_bytes()).hexdigest()
                    h2 = hashlib.md5(flat_target.read_bytes()).hexdigest()
                    if h1 == h2:
                        log.append(f"  SKIP (identical): {child.name}/{rel}")
                        if execute:
                            nested_file.unlink()
                    else:
                        log.append(f"  ❌ CONFLICT (different): {child.name}/{rel}")
                        # Don't move — manual resolution needed
                else:
                    log.append(f"  MERGE: {child.name}/{rel}")
                    if execute:
                        flat_target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(nested_file), str(flat_target))
        else:
            # No conflict — just move the whole dir
            log.append(f"  MOVE dir: {child.name}/ ({len(list(child.rglob('*')))} items)")
            if execute:
                shutil.move(str(child), str(target))

    # Remove the now-empty ticker dir
    if execute:
        # Remove any remaining empty subdirs
        for d in sorted(ticker_dir.rglob("*"), reverse=True):
            if d.is_dir():
                try:
                    d.rmdir()
                except OSError:
                    pass
        try:
            ticker_dir.rmdir()
            log.append(f"  REMOVED: {ticker_dir.name}/")
        except OSError as e:
            log.append(f"  ⚠️  Could not remove {ticker_dir.name}/: {e}")
    else:
        log.append(f"  WOULD REMOVE: {ticker_dir.name}/")

    return log


def refresh_sources_index(sources_dir: Path, *, execute: bool) -> str | None:
    """Regenerate INDEX.md for a sources directory."""
    idx = sources_dir / "INDEX.md"
    dirs = sorted(d.name for d in sources_dir.iterdir() if d.is_dir() and not d.name.startswith("."))
    files = sorted(f.name for f in sources_dir.iterdir() if f.is_file() and f.name != "INDEX.md" and not f.name.startswith("."))

    lines = ["# Index: sources", "", "## Directories", ""]
    if dirs:
        for d in dirs:
            lines.append(f"- [{d}/](./{d}/)")
    else:
        lines.append("- (none)")
    lines.extend(["", "## Files", ""])
    if files:
        for f in files:
            lines.append(f"- [{f}](./{f})")
    else:
        lines.append("- (none)")
    lines.append("")

    content = "\n".join(lines)
    if execute:
        idx.write_text(content, encoding="utf-8")
    return content


def main():
    parser = argparse.ArgumentParser(description="Flatten ticker-nested source directories")
    parser.add_argument("--execute", action="store_true", help="Actually perform the moves (default: dry-run)")
    args = parser.parse_args()

    mode = "EXECUTE" if args.execute else "DRY-RUN"
    print(f"=== Ticker Nesting Cleanup ({mode}) ===\n")

    targets = find_ticker_dirs()
    if not targets:
        print("No ticker-nested directories found. Nothing to do.")
        return

    # Pre-flight conflict check
    has_blocking_conflict = False
    for t in targets:
        conflicts = check_conflicts(t["ticker_dir"], t["sources_dir"])
        diff_conflicts = [c for c in conflicts if not c["same_hash"]]
        if diff_conflicts:
            has_blocking_conflict = True
            print(f"❌ BLOCKING CONFLICT in {t['company']}:")
            for c in diff_conflicts:
                print(f"   {c['rel']}: nested ≠ flat (different content)")

    if has_blocking_conflict:
        print("\nAborting: resolve conflicts above before running with --execute")
        sys.exit(1)

    # Process each
    total_moved = 0
    for t in targets:
        print(f"{t['company']} — {t['ticker']}/ → flatten")
        log = flatten_one(t["ticker_dir"], t["sources_dir"], execute=args.execute)
        for line in log:
            print(line)
        total_moved += 1

        # Refresh INDEX.md
        refresh_sources_index(t["sources_dir"], execute=args.execute)
        if args.execute:
            print("  REFRESHED: INDEX.md")
        else:
            print("  WOULD REFRESH: INDEX.md")
        print()

    print(f"{'Processed' if args.execute else 'Would process'}: {total_moved} folders")
    if not args.execute:
        print("\nRe-run with --execute to apply changes.")


if __name__ == "__main__":
    main()
