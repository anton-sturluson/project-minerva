"""Check tracked text for private configuration and personal identifiers; never print values."""

import re
import subprocess
from pathlib import Path

EMAIL = re.compile(rb"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
EXAMPLE_DOMAINS = {
    b"example.com",
    b"example.org",
    b"example.net",
    b"example.invalid",
    b"users.noreply.github.com",
}
PATTERNS = {
    "private Slack mention": re.compile(rb"<@[UW][A-Z0-9]{8,}>"),
    "personal home directory": re.compile(
        rb"(?<![A-Za-z0-9_/])/(?:Users|home)/(?!user\b|username\b|runner\b)[A-Za-z0-9_.-]+"
    ),
    "encoded personal home directory": re.compile(
        rb"-Users-[A-Za-z0-9-]+-(?:Documents|Desktop|Downloads)-"
    ),
    "private tailnet address": re.compile(
        rb"\b[a-z0-9-]+\.tail[0-9a-f]{6}\.ts\.net\b", re.IGNORECASE
    ),
    "document sharing identifier": re.compile(
        rb"docs\.google\.com/(?:spreadsheets|document|presentation)/d/[A-Za-z0-9_-]{20,}"
    ),
}
PRIVATE_DIRS = {"hard-disk", "data", "worktrees", ".worktrees"}
PRIVATE_NAMES = {"id_rsa", "id_ed25519", "credentials.json", "credentials.toml"}
PRIVATE_SUFFIXES = {
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".dump",
    ".sqlite",
    ".sqlite3",
    ".db",
}


def main():
    root = Path(
        subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], text=True
        ).strip()
    )
    files = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).split(b"\0")
    findings = []
    for name in files:
        if not name:
            continue
        relative = name.decode()
        path = root / relative
        if not path.exists() or path.is_symlink():
            continue
        if (
            path.name in PRIVATE_NAMES
            or path.suffix in PRIVATE_SUFFIXES
            or (path.name.startswith(".env") and not path.name.endswith(".example"))
        ):
            findings.append((relative, 0, "private configuration filename"))
        data = path.read_bytes()
        if b"\0" in data:
            continue
        for number, line in enumerate(data.splitlines(), 1):
            for rule, pattern in PATTERNS.items():
                if pattern.search(line):
                    findings.append((relative, number, rule))
            if any(
                m.group(1).lower() not in EXAMPLE_DOMAINS for m in EMAIL.finditer(line)
            ):
                findings.append((relative, number, "non-example email address"))
    for path, line, rule in findings:
        print(f"{path}:{line}: {rule} (value redacted)")
    print(f"Tracked-file privacy check: {len(findings)} finding(s).")
    return bool(findings)


if __name__ == "__main__":
    raise SystemExit(main())
