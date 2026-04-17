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
PORTFOLIO_CURRENT_DIR="${MINERVA_WORKSPACE_ROOT}/data/01-portfolio/current"
MACRO_REGISTRY_PATH="${MINERVA_BRIEF_MACRO_REGISTRY:-${PORTFOLIO_CURRENT_DIR}/macro-registry.json}"
IR_REGISTRY_PATH="${MINERVA_BRIEF_IR_REGISTRY:-${PORTFOLIO_CURRENT_DIR}/ir-registry.json}"
GENERATED_MACRO_SOURCE="${MINERVA_WORKSPACE_ROOT}/reports/03-daily-news/${RUN_DATE}/data/raw/macro-events.json"

IFS=' ' read -r -a MINERVA_RUNNER_ARR <<< "${MINERVA_RUNNER}"

mkdir -p "${MINERVA_WORKSPACE_ROOT}/reports/03-daily-news/${RUN_DATE}"

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

MACRO_SOURCE_PATH="${MINERVA_BRIEF_MACRO_SOURCE:-${GENERATED_MACRO_SOURCE}}"
if [[ -z "${MINERVA_BRIEF_MACRO_SOURCE:-}" ]]; then
  run brief macro-collect --date "${RUN_DATE}" --registry "${MACRO_REGISTRY_PATH}" --output "${MACRO_SOURCE_PATH}"
fi

macro_args=(brief macro --date "${RUN_DATE}" --registry "${MACRO_REGISTRY_PATH}" --source "${MACRO_SOURCE_PATH}")
run "${macro_args[@]}"

ir_args=(brief ir --date "${RUN_DATE}" --registry "${IR_REGISTRY_PATH}")
run "${ir_args[@]}"

market_args=(brief market --date "${RUN_DATE}" --provider "${MINERVA_BRIEF_MARKET_PROVIDER}")
if [[ -n "${MINERVA_BRIEF_MARKET_SOURCE:-}" ]]; then
  market_args+=(--source "${MINERVA_BRIEF_MARKET_SOURCE}")
fi
run "${market_args[@]}"

# ── Browser fallback for blocked IR/macro sources ──
MINERVA_SKIP_BROWSER_FALLBACK="${MINERVA_SKIP_BROWSER_FALLBACK:-0}"
MANIFEST_PATH_CHECK="${MINERVA_WORKSPACE_ROOT}/reports/03-daily-news/${RUN_DATE}/data/raw/manifest.json"
BROWSER_OUTPUT_DIR="${MINERVA_WORKSPACE_ROOT}/reports/03-daily-news/${RUN_DATE}/data/raw"

if [[ "${MINERVA_SKIP_BROWSER_FALLBACK}" != "1" ]]; then
  FAILED_TICKERS=$(uv run python - "${MANIFEST_PATH_CHECK}" "${IR_REGISTRY_PATH}" <<'PY'
import json
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
registry_path = Path(sys.argv[2])

if not manifest_path.exists():
    sys.exit(0)

manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
ir_source = manifest.get("sources", {}).get("ir", {})

if ir_source.get("error_count", 0) == 0:
    sys.exit(0)

ir_raw_path = ir_source.get("raw_path", "")
if not ir_raw_path or not Path(ir_raw_path).exists():
    sys.exit(0)

ir_raw = json.loads(Path(ir_raw_path).read_text(encoding="utf-8"))
errors = ir_raw.get("errors", [])
if not errors:
    sys.exit(0)

registry = json.loads(registry_path.read_text(encoding="utf-8")) if registry_path.exists() else []
reg_lookup = {}
for entry in registry:
    sid = entry.get("security_id", "")
    feeds = entry.get("feeds", [])
    if sid and feeds:
        reg_lookup[sid] = feeds[0].get("url", "")

lines = []
for err in errors:
    sid = err.get("security_id", "")
    url = reg_lookup.get(sid, err.get("url", ""))
    if sid and url:
        lines.append(f"- {sid}: {url}")

if lines:
    print("\n".join(lines))
PY
  ) || true

  if [[ -n "${FAILED_TICKERS}" ]]; then
    echo "browser_fallback: found blocked IR sources, spawning browser agent..."
    echo "${FAILED_TICKERS}"
    BROWSER_OUTPUT="${BROWSER_OUTPUT_DIR}/ir-browser.json"
    openclaw agent \
      --agent main \
      --timeout 1200 \
      --thinking medium \
      --json \
      --message "Browser IR fallback for ${RUN_DATE}.

The following IR pages were blocked during HTTP collection (Cloudflare, bot protection, or timeouts). Use the browser skill to visit each page, find press releases or news items published on ${RUN_DATE}, and extract: headline, date, URL, and a brief summary of the content if visible.

Write the results as a JSON file to: ${BROWSER_OUTPUT}

The JSON should have this structure:
{\"date\": \"${RUN_DATE}\", \"collected_at\": \"<ISO timestamp>\", \"fetch_method\": \"browser\", \"events\": [{\"source\": \"ir\", \"event_type\": \"ir\", \"event_date\": \"${RUN_DATE}\", \"security_id\": \"<TICKER>\", \"relationship\": \"monitored\", \"headline\": \"<title>\", \"reference_url\": \"<link>\", \"metadata\": {}}]}

If a page has no press releases for ${RUN_DATE}, include an empty events array for that ticker. If you cannot access a page even with the browser, note it in the metadata.

Failed tickers:
${FAILED_TICKERS}" 2>&1 || echo "browser_fallback: openclaw agent failed (non-fatal), continuing without browser results"
    echo "browser_fallback: done"
  else
    echo "browser_fallback: no blocked IR sources detected"
  fi
fi

run brief prep --date "${RUN_DATE}"

PREPARED_PATH="${MINERVA_WORKSPACE_ROOT:-hard-disk}/reports/03-daily-news/${RUN_DATE}/data/structured/prepared-evidence.json"
MANIFEST_PATH="${MINERVA_WORKSPACE_ROOT:-hard-disk}/reports/03-daily-news/${RUN_DATE}/data/raw/manifest.json"

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
