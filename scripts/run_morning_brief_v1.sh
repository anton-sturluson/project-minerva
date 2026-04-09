#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export UV_CACHE_DIR="${UV_CACHE_DIR:-${ROOT_DIR}/.uv-cache}"
export MINERVA_WORKSPACE_ROOT="${MINERVA_WORKSPACE_ROOT:-${ROOT_DIR}/hard-disk}"

RUN_DATE="${1:-$(date +%F)}"
WITH_POST_WRITE="${MINERVA_WITH_POST_WRITE:-0}"
MINERVA_RUNNER="${MINERVA_RUNNER:-uv run minerva}"
MINERVA_SKIP_STATUS_CHECK="${MINERVA_SKIP_STATUS_CHECK:-0}"
MINERVA_BRIEF_EARNINGS_PROVIDER="${MINERVA_BRIEF_EARNINGS_PROVIDER:-auto}"
MINERVA_BRIEF_MARKET_PROVIDER="${MINERVA_BRIEF_MARKET_PROVIDER:-auto}"

IFS=' ' read -r -a MINERVA_RUNNER_ARR <<< "${MINERVA_RUNNER}"

mkdir -p "${MINERVA_WORKSPACE_ROOT}/reports/daily-news/${RUN_DATE}"

run() {
  "${MINERVA_RUNNER_ARR[@]}" "$@"
}

portfolio_sync_args=(portfolio sync --date "${RUN_DATE}")
if [[ -n "${MINERVA_PORTFOLIO_HOLDINGS_SOURCE:-}" ]]; then
  portfolio_sync_args+=(--holdings-source "${MINERVA_PORTFOLIO_HOLDINGS_SOURCE}")
fi
if [[ -n "${MINERVA_PORTFOLIO_TRANSACTIONS_SOURCE:-}" ]]; then
  portfolio_sync_args+=(--transactions-source "${MINERVA_PORTFOLIO_TRANSACTIONS_SOURCE}")
fi
if [[ -n "${MINERVA_PORTFOLIO_WATCHLIST_SOURCE:-}" ]]; then
  portfolio_sync_args+=(--watchlist-source "${MINERVA_PORTFOLIO_WATCHLIST_SOURCE}")
fi
run "${portfolio_sync_args[@]}"

filings_args=(brief filings --date "${RUN_DATE}")
if [[ -n "${MINERVA_BRIEF_FILINGS_SOURCE:-}" ]]; then
  filings_args+=(--source "${MINERVA_BRIEF_FILINGS_SOURCE}")
fi
run "${filings_args[@]}"

earnings_args=(brief earnings --date "${RUN_DATE}" --provider "${MINERVA_BRIEF_EARNINGS_PROVIDER}")
if [[ -n "${MINERVA_BRIEF_EARNINGS_SOURCE:-}" ]]; then
  earnings_args+=(--source "${MINERVA_BRIEF_EARNINGS_SOURCE}")
fi
run "${earnings_args[@]}"

macro_args=(brief macro --date "${RUN_DATE}")
if [[ -n "${MINERVA_BRIEF_MACRO_SOURCE:-}" ]]; then
  macro_args+=(--source "${MINERVA_BRIEF_MACRO_SOURCE}")
fi
if [[ -n "${MINERVA_BRIEF_MACRO_REGISTRY:-}" ]]; then
  macro_args+=(--registry "${MINERVA_BRIEF_MACRO_REGISTRY}")
fi
run "${macro_args[@]}"

ir_args=(brief ir --date "${RUN_DATE}")
if [[ -n "${MINERVA_BRIEF_IR_REGISTRY:-}" ]]; then
  ir_args+=(--registry "${MINERVA_BRIEF_IR_REGISTRY}")
fi
run "${ir_args[@]}"

market_args=(brief market --date "${RUN_DATE}" --provider "${MINERVA_BRIEF_MARKET_PROVIDER}")
if [[ -n "${MINERVA_BRIEF_MARKET_SOURCE:-}" ]]; then
  market_args+=(--source "${MINERVA_BRIEF_MARKET_SOURCE}")
fi
run "${market_args[@]}"

run brief prep --date "${RUN_DATE}"

PREPARED_PATH="${MINERVA_WORKSPACE_ROOT:-hard-disk}/reports/daily-news/${RUN_DATE}/data/structured/prepared-evidence.json"
MANIFEST_PATH="${MINERVA_WORKSPACE_ROOT:-hard-disk}/reports/daily-news/${RUN_DATE}/data/raw/manifest.json"

if [[ "${MINERVA_SKIP_STATUS_CHECK}" != "1" ]]; then
  uv run python - "${MANIFEST_PATH}" <<'PY'
import json
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
sources = manifest.get("sources", {})
required = ["filings", "earnings", "macro", "ir", "market", "prep"]
missing = [name for name in required if name not in sources]
blocking = [name for name in required if sources.get(name, {}).get("status") == "error"]
if missing:
    print(f"missing manifest source entries: {', '.join(missing)}", file=sys.stderr)
    raise SystemExit(1)
if blocking:
    print(f"blocking morning-brief collection errors: {', '.join(blocking)}", file=sys.stderr)
    raise SystemExit(1)
PY
fi

echo "prepared_evidence: ${PREPARED_PATH}"
echo "manifest: ${MANIFEST_PATH}"
echo "main_agent_step: write notes/morning-brief-report.md and notes/slack-brief.md from the prepared evidence"

if [[ "${WITH_POST_WRITE}" == "1" ]]; then
  run brief audit --date "${RUN_DATE}"
  run brief review-log --date "${RUN_DATE}"
fi
