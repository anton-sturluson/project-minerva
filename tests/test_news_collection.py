"""Behavioral coverage for isolated morning-brief news collectors."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_SCRIPT = REPO_ROOT / "scripts" / "run_morning_brief.sh"


def _write_executable(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)
    return path


def _fake_runner(tmp_path: Path) -> Path:
    return _write_executable(
        tmp_path / "fake-minerva",
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "news" && "${2:-}" == "ingest" ]]; then
  raw_dir=""
  shift 2
  while [[ "$#" -gt 0 ]]; do
    if [[ "$1" == "--raw-dir" ]]; then
      raw_dir="$2"
      shift 2
    else
      shift
    fi
  done
  mkdir -p "${CAPTURE_DIR}"
  for artifact in "${raw_dir}/"*.md; do
    [[ -f "${artifact}" ]] || continue
    cp "${artifact}" "${CAPTURE_DIR}/${artifact##*/}"
  done
  printf '{"eligible": 100}\n'
fi
""",
    )


def _fake_openclaw(tmp_path: Path) -> Path:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    return _write_executable(
        fake_bin / "openclaw",
        r'''#!/usr/bin/env bash
set -euo pipefail
message=""
timeout=""
while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --message)
      message="$2"
      shift 2
      ;;
    --timeout)
      timeout="$2"
      shift 2
      ;;
    *)
      shift
      ;;
  esac
done
source_root=$(printf '%s\n' "${message}" | sed -n 's/^Your isolated source root is `\([^`]*\)`.*/\1/p' | head -n 1)
source_id="${source_root##*/}"
printf '%s|%s\n' "${source_id}" "${timeout}" >> "${TIMEOUT_LOG}"

if [[ "${source_id}" == "${BROKEN_SOURCE:-}" ]]; then
  exit 7
fi

if [[ "${source_id}" == ir-* ]]; then
  printf '%s\n' "${source_id}" >> "${IR_START_LOG}"
  for _ in $(seq 1 500); do
    started=$(wc -l < "${IR_START_LOG}" | tr -d ' ')
    [[ "${started}" -ge "${EXPECTED_IR_COUNT:-0}" ]] && break
    sleep 0.01
  done
  started=$(wc -l < "${IR_START_LOG}" | tr -d ' ')
  [[ "${started}" -ge "${EXPECTED_IR_COUNT:-0}" ]] || exit 8
  if [[ "${COLLIDE:-0}" == "1" ]]; then
    filename="collision.md"
  else
    filename="${source_id}-story.md"
  fi
  printf 'artifact from %s\n' "${source_id}" > "${source_root}/raw/${filename}"
  if [[ "${source_id}" == "ir-AMD" ]]; then
    : > "${AMD_READY}"
  fi
  exit 0
fi

if [[ "${source_id}" == "reuters-markets" ]]; then
  for _ in $(seq 1 500); do
    [[ -f "${AMD_READY}" ]] && break
    sleep 0.01
  done
  [[ -f "${AMD_READY}" ]] || exit 9
  printf 'file deliberately removed by Reuters\n' > "${source_root}/raw/reuters-old.md"
  printf '%s\n' "${source_root}/raw" > "${DELETION_ROOT_LOG}"
  find "${source_root}/raw" -maxdepth 1 -type f -delete
fi

if [[ "${COLLIDE:-0}" == "1" ]]; then
  filename="collision.md"
else
  filename="${source_id}-story.md"
fi
printf 'artifact from %s\n' "${source_id}" > "${source_root}/raw/${filename}"
''',
    )


def _run_wrapper(
    tmp_path: Path,
    *,
    sources: list[dict[str, object]],
    ir_entries: list[dict[str, object]],
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    sources_path = tmp_path / "news-sources.json"
    sources_path.write_text(json.dumps(sources), encoding="utf-8")
    ir_path = tmp_path / "ir-registry.json"
    ir_path.write_text(json.dumps(ir_entries), encoding="utf-8")

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    temp_state = tmp_path / "tmp"
    temp_state.mkdir()
    capture_dir = tmp_path / "captured"
    coordinator = tmp_path / "coordinator"
    coordinator.mkdir()
    fake_openclaw = _fake_openclaw(tmp_path)
    fake_runner = _fake_runner(tmp_path)

    env = os.environ.copy()
    env.update(
        {
            "HOME": str(fake_home),
            "PATH": f"{fake_openclaw.parent}:{env['PATH']}",
            "TMPDIR": str(temp_state),
            "MINERVA_RUNNER": str(fake_runner),
            "MINERVA_NEWS_SOURCES": str(sources_path),
            "MINERVA_IR_REGISTRY": str(ir_path),
            "MINERVA_SKIP_STATUS_CHECK": "1",
            "MINERVA_ALLOW_THIN_BRIEF": "1",
            "MINERVA_WORKSPACE_ROOT": str(tmp_path / "workspace"),
            "INVEST_DB": str(tmp_path / "invest.db"),
            "CAPTURE_DIR": str(capture_dir),
            "TIMEOUT_LOG": str(coordinator / "timeouts.log"),
            "IR_START_LOG": str(coordinator / "ir-starts.log"),
            "AMD_READY": str(coordinator / "amd-ready"),
            "DELETION_ROOT_LOG": str(coordinator / "deletion-root.log"),
        }
    )
    if extra_env:
        env.update(extra_env)

    run_date = f"test-{tmp_path.name}"
    report_dir = (
        REPO_ROOT / "hard-disk" / "reports" / "03-daily-news" / run_date
    )
    try:
        return subprocess.run(
            ["bash", str(PIPELINE_SCRIPT), run_date],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    finally:
        shutil.rmtree(report_dir, ignore_errors=True)


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("MINERVA_BROWSER_TIMEOUT", "0"),
        ("MINERVA_BROWSER_TIMEOUT", "not-a-number"),
        ("MINERVA_WEBFETCH_TIMEOUT", "-1"),
        ("MINERVA_MAX_COLLECTORS", "0"),
    ],
)
def test_collector_timeout_validation_precedes_temp_state(
    tmp_path: Path, variable: str, value: str
) -> None:
    temp_state = tmp_path / "tmp"
    temp_state.mkdir()
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    env = os.environ.copy()
    env.update({"HOME": str(fake_home), "TMPDIR": str(temp_state), variable: value})

    result = subprocess.run(
        ["bash", str(PIPELINE_SCRIPT), "test-invalid-timeout"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )

    assert result.returncode == 1
    assert f"{variable} must be a positive integer" in result.stderr
    assert list(temp_state.iterdir()) == []


def test_collectors_are_isolated_launch_all_ir_and_aggregate_every_artifact(
    tmp_path: Path,
) -> None:
    tickers = ["AMD", "ONE", "TWO", "THREE", "FOUR", "FIVE"]
    sources = [
        {
            "id": "reuters-markets",
            "name": "Reuters Markets",
            "url": "https://example.test/reuters",
            "access": "browser",
        },
        {
            "id": "broken-feed",
            "name": "Broken Feed",
            "url": "https://example.test/broken",
            "access": "web_fetch",
        },
    ]
    ir_entries = [
        {
            "security_id": ticker,
            "company_name": ticker,
            "feeds": [{"url": f"https://example.test/{ticker}"}],
        }
        for ticker in tickers
    ]

    result = _run_wrapper(
        tmp_path,
        sources=sources,
        ir_entries=ir_entries,
        extra_env={
            "EXPECTED_IR_COUNT": str(len(tickers)),
            "BROKEN_SOURCE": "broken-feed",
            "MINERVA_MAX_COLLECTORS": "8",
        },
    )

    assert result.returncode == 0, result.stderr
    captured = {path.name for path in (tmp_path / "captured").glob("*.md")}
    assert captured == {
        "broken-feed-error.md",
        "reuters-markets-story.md",
        *(f"ir-{ticker}-story.md" for ticker in tickers),
    }
    assert (tmp_path / "captured" / "ir-AMD-story.md").read_text(
        encoding="utf-8"
    ) == "artifact from ir-AMD\n"

    deletion_root = (tmp_path / "coordinator" / "deletion-root.log").read_text(
        encoding="utf-8"
    ).strip()
    assert deletion_root.endswith("/sources/reuters-markets/raw")
    assert "/sources/ir-AMD/raw" != deletion_root

    ir_starts = (
        tmp_path / "coordinator" / "ir-starts.log"
    ).read_text(encoding="utf-8").splitlines()
    assert set(ir_starts) == {f"ir-{ticker}" for ticker in tickers}

    timeout_rows = (
        tmp_path / "coordinator" / "timeouts.log"
    ).read_text(encoding="utf-8").splitlines()
    timeout_by_source = dict(row.split("|", 1) for row in timeout_rows)
    assert timeout_by_source["broken-feed"] == "300"
    assert timeout_by_source["reuters-markets"] == "900"
    assert all(timeout_by_source[f"ir-{ticker}"] == "900" for ticker in tickers)


def test_aggregation_rejects_cross_source_filename_collision(tmp_path: Path) -> None:
    sources = [
        {
            "id": source_id,
            "name": source_id,
            "url": f"https://example.test/{source_id}",
            "access": "browser",
        }
        for source_id in ("source-a", "source-b")
    ]

    result = _run_wrapper(
        tmp_path,
        sources=sources,
        ir_entries=[],
        extra_env={"COLLIDE": "1", "EXPECTED_IR_COUNT": "0"},
    )

    assert result.returncode == 1
    assert "news: raw filename collision: collision.md" in result.stderr
    assert not (tmp_path / "captured").exists()

    match = re.search(r"^news_run_dir: (.+)$", result.stdout, flags=re.MULTILINE)
    assert match is not None
    shutil.rmtree(match.group(1), ignore_errors=True)
