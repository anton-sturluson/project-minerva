#!/usr/bin/env bash

# Source env for API keys BEFORE strict mode
# zshrc contains zsh-specific commands (setopt) that fail in bash with set -e
source ~/.zshrc >/dev/null 2>&1 || true

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.."; pwd)"
RUN_DATE="${1:-$(date +%F)}"
MINERVA_IR_BATCH_SIZE="${MINERVA_IR_BATCH_SIZE:-5}"
if ! [[ "${MINERVA_IR_BATCH_SIZE}" =~ ^[1-9][0-9]*$ ]]; then
  echo "MINERVA_IR_BATCH_SIZE must be a positive integer" >&2
  exit 1
fi

# Ephemeral run directory: raw articles + per-article summaries live here for
# the duration of one run, get ingested into invest.db, then are removed.
# Parallel collector agents write markdown here; only the final ingest process
# writes SQLite.
NEWS_RUN_DIR="$(mktemp -d "${TMPDIR:-/tmp}/morning-brief-${RUN_DATE}-XXXXXX")"
# NEWS_DIR is what collector prompts and extract-files see. Point it at the
# temp run dir so their outputs are ephemeral.
NEWS_DIR="${NEWS_RUN_DIR}"
REPORT_DIR="${ROOT_DIR}/hard-disk/reports/03-daily-news/${RUN_DATE}"
INVEST_DB="${INVEST_DB:-${ROOT_DIR}/hard-disk/data/04-database/invest.db}"
INGEST_OK=0
cleanup_run_dir() {
  # Remove the temp run dir only when ingest into invest.db succeeded.
  # Otherwise leave it for debugging.
  if [[ "${INGEST_OK}" == "1" && -d "${NEWS_RUN_DIR}" ]]; then
    rm -rf "${NEWS_RUN_DIR}"
  fi
}
trap cleanup_run_dir EXIT

export UV_CACHE_DIR="${UV_CACHE_DIR:-${ROOT_DIR}/.uv-cache}"
export MINERVA_WORKSPACE_ROOT="${MINERVA_WORKSPACE_ROOT:-${ROOT_DIR}/hard-disk}"

MINERVA_RUNNER="${MINERVA_RUNNER:-uv run minerva}"
MINERVA_BRIEF_EARNINGS_PROVIDER="${MINERVA_BRIEF_EARNINGS_PROVIDER:-finnhub}"
MINERVA_BRIEF_MARKET_PROVIDER="${MINERVA_BRIEF_MARKET_PROVIDER:-finnhub}"
MINERVA_SKIP_STATUS_CHECK="${MINERVA_SKIP_STATUS_CHECK:-0}"
MINERVA_SKIP_NEWS="${MINERVA_SKIP_NEWS:-0}"
MINERVA_ALLOW_THIN_BRIEF="${MINERVA_ALLOW_THIN_BRIEF:-0}"

IFS=' ' read -r -a MINERVA_RUNNER_ARR <<< "${MINERVA_RUNNER}"
printf -v NEWS_EXIST_RUNNER '%q ' "${MINERVA_RUNNER_ARR[@]}" news exist
NEWS_EXIST_RUNNER="${NEWS_EXIST_RUNNER% }"
# Collector agents run from their OpenClaw workspace, not necessarily this
# repository. Anchor the CLI command here so `uv run minerva` resolves the
# checked-out project rather than a stale globally installed Minerva tool.
printf -v NEWS_EXIST_COMMAND 'cd %q && %s' "${ROOT_DIR}" "${NEWS_EXIST_RUNNER}"

run() { "${MINERVA_RUNNER_ARR[@]}" "$@"; }

mkdir -p \
  "${REPORT_DIR}" \
  "${NEWS_DIR}/raw" \
  "${NEWS_DIR}/summaries" \
  "${NEWS_DIR}/logs" \
  "${NEWS_DIR}/candidates" \
  "${NEWS_DIR}/lookups"

echo "=== Morning Brief Pipeline ==="
echo "date: ${RUN_DATE}"
echo "news_run_dir: ${NEWS_RUN_DIR}"
echo "invest_db: ${INVEST_DB}"
echo "report_dir: ${REPORT_DIR}"
echo ""

# ── PHASE 1: Structured data collection ──
echo "── Phase 1: Structured data ──"

portfolio_sync_args=(portfolio sync --date "${RUN_DATE}")
[[ -n "${MINERVA_PORTFOLIO_HOLDINGS_SOURCE:-}" ]] && portfolio_sync_args+=(--holdings-source "${MINERVA_PORTFOLIO_HOLDINGS_SOURCE}")
[[ -n "${MINERVA_PORTFOLIO_TRANSACTIONS_SOURCE:-}" ]] && portfolio_sync_args+=(--transactions-source "${MINERVA_PORTFOLIO_TRANSACTIONS_SOURCE}")
[[ -n "${MINERVA_PORTFOLIO_WATCHLIST_SOURCE:-}" ]] && portfolio_sync_args+=(--watchlist-source "${MINERVA_PORTFOLIO_WATCHLIST_SOURCE}")
run "${portfolio_sync_args[@]}"

run brief filings --date "${RUN_DATE}"

earnings_args=(brief earnings --date "${RUN_DATE}" --provider "${MINERVA_BRIEF_EARNINGS_PROVIDER}")
[[ -n "${MINERVA_BRIEF_EARNINGS_SOURCE:-}" ]] && earnings_args+=(--source "${MINERVA_BRIEF_EARNINGS_SOURCE}")
run "${earnings_args[@]}"

market_args=(brief market --date "${RUN_DATE}" --provider "${MINERVA_BRIEF_MARKET_PROVIDER}")
[[ -n "${MINERVA_BRIEF_MARKET_SOURCE:-}" ]] && market_args+=(--source "${MINERVA_BRIEF_MARKET_SOURCE}")
run "${market_args[@]}"

echo ""

# ── PHASE 2a: News collection (parallel browser/web_fetch agents) ──
if [[ "${MINERVA_SKIP_NEWS}" == "1" ]]; then
  echo "── Phase 2a: News collection (skipped) ──"
else
  echo "── Phase 2a: News collection ──"

  BROWSER_PROMPT_TEMPLATE="${ROOT_DIR}/scripts/prompts/collect_news.md"
  WEBFETCH_PROMPT_TEMPLATE="${ROOT_DIR}/scripts/prompts/collect_news_webfetch.md"
  NEWS_SOURCES="${ROOT_DIR}/hard-disk/data/02-news/news-sources.json"
  IR_REGISTRY="${ROOT_DIR}/hard-disk/data/01-portfolio/current/ir-registry.json"
  NEWS_LOG_DIR="${NEWS_RUN_DIR}/logs"
  PIDS=()

  if [[ -f "${NEWS_SOURCES}" ]] && ! jq -e '
    type == "array" and all(.[];
      type == "object" and
      (.id | type == "string" and length > 0) and
      (.name | type == "string" and length > 0) and
      (.url | type == "string" and length > 0) and
      (.access == "browser" or .access == "web_fetch") and
      ((has("collect") | not) or (.collect | type == "string"))
    )
  ' "${NEWS_SOURCES}" >/dev/null; then
    echo "news: malformed source registry: ${NEWS_SOURCES}" >&2
    exit 1
  fi
  if [[ -f "${IR_REGISTRY}" ]] && ! jq -e '
    type == "array" and all(.[];
      type == "object" and
      (.security_id | type == "string" and length > 0) and
      (.company_name | type == "string" and length > 0) and
      (.feeds | type == "array") and
      all(.feeds[]; type == "object" and (.url | type == "string" and length > 0))
    )
  ' "${IR_REGISTRY}" >/dev/null; then
    echo "news: malformed IR registry: ${IR_REGISTRY}" >&2
    exit 1
  fi

  write_collection_error() {
    local source_id="$1" source_name="$2" url="$3" sessid="$4" status="$5" log_file="$6"
    local error_file="${NEWS_DIR}/raw/${source_id}-error.md"

    cat > "${error_file}" <<EOF
# ${source_name} collection failed

Source: ${source_name}
URL: ${url}
Published: ${RUN_DATE}
Collected: $(date -u +%FT%TZ)
Section: collection-error

Status: failed
Exit status: ${status}
Session: ${sessid}
Log: ${log_file}

The collector exited non-zero. See the log file above for stdout/stderr from the child collector process.
EOF
  }

  # ── Build portfolio company list (ticker + name) ──
  COMPANY_DIR="${ROOT_DIR}/hard-disk/data/01-portfolio/current/company-directory.md"
  RENDERED_PORTFOLIO="${ROOT_DIR}/hard-disk/data/01-portfolio/current/rendered.md"
  PORTFOLIO_TICKERS="(not available)"
  if [[ -f "$COMPANY_DIR" && -f "$RENDERED_PORTFOLIO" ]]; then
    # Get active tickers from rendered.md (holdings + watchlist)
    active_tickers=$(grep -E '^- `[A-Z0-9.]+`' "$RENDERED_PORTFOLIO" | sed 's/- `\([^`]*\)`.*/\1/' | sort -u)
    # Look up company names from the directory table, output "Ticker — Company Name"
    PORTFOLIO_TICKERS=""
    while read -r tkr; do
      name=$(grep -E "^\| ${tkr} \|" "$COMPANY_DIR" 2>/dev/null | head -1 | awk -F'|' '{gsub(/^ +| +$/, "", $3); print $3}' || true)
      if [[ -n "$name" ]]; then
        entry="${name}"
      else
        entry="${tkr}"
      fi
      if [[ -n "$PORTFOLIO_TICKERS" ]]; then
        PORTFOLIO_TICKERS="${PORTFOLIO_TICKERS}, ${entry}"
      else
        PORTFOLIO_TICKERS="${entry}"
      fi
    done <<< "$active_tickers"
    echo "  portfolio: ${PORTFOLIO_TICKERS}"
  elif [[ -f "$RENDERED_PORTFOLIO" ]]; then
    PORTFOLIO_TICKERS=$(grep -E '^- `[A-Z0-9.]+`' "$RENDERED_PORTFOLIO" | sed 's/- `\([^`]*\)`.*/\1/' | sort -u | tr '\n' ', ' | sed 's/,$//')
    echo "  portfolio tickers (no names): ${PORTFOLIO_TICKERS}"
  fi

  render_collection_prompt() {
    local template="$1" source_name="$2" source_id="$3" url="$4" collection_scope="$5"
    local candidate_file="${NEWS_DIR}/candidates/${source_id}.json"
    local lookup_file="${NEWS_DIR}/lookups/${source_id}.json"
    python3 - "$template" "$RUN_DATE" "$source_name" "$source_id" "$url" \
      "$NEWS_DIR" "$INVEST_DB" "$NEWS_EXIST_COMMAND" "$PORTFOLIO_TICKERS" \
      "$collection_scope" "$candidate_file" "$lookup_file" <<'PY'
import sys
from pathlib import Path

(
    template,
    run_date,
    source_name,
    source_id,
    url,
    news_dir,
    invest_db,
    news_exist_command,
    portfolio_tickers,
    collection_scope,
    candidate_file,
    lookup_file,
) = sys.argv[1:]
text = Path(template).read_text(encoding="utf-8")
replacements = {
    "DATE": run_date,
    "SOURCE_NAME": source_name,
    "SOURCE_ID": source_id,
    "URL": url,
    "NEWS_DIR": news_dir,
    "INVEST_DB": invest_db,
    "NEWS_EXIST_COMMAND": news_exist_command,
    "PORTFOLIO_TICKERS": portfolio_tickers,
    "COLLECT_SCOPE": collection_scope,
    "CANDIDATE_FILE": candidate_file,
    "LOOKUP_FILE": lookup_file,
}
for name, value in replacements.items():
    text = text.replace("{{" + name + "}}", value)
sys.stdout.write(text)
PY
  }

  # Spawn one collector. Prompt template and timeout preserve the browser and
  # web_fetch collectors' different behavior without duplicating process logic.
  collect_source() {
    local prompt_template="$1" timeout="$2" source_id="$3" source_name="$4"
    local url="$5" collection_scope="$6"
    local sessid="news-${source_id}-$(date +%s)"
    local log_file="${NEWS_LOG_DIR}/${source_id}.log"
    local prompt
    prompt=$(render_collection_prompt "${prompt_template}" \
      "$source_name" "$source_id" "$url" "$collection_scope")

    {
      echo "source_id: ${source_id}"
      echo "source_name: ${source_name}"
      echo "url: ${url}"
      echo "session_id: ${sessid}"
      echo "started_at: $(date -u +%FT%TZ)"
      echo ""
    } > "${log_file}"

    if openclaw agent \
      --agent main \
      --timeout "${timeout}" \
      --model fireworks/accounts/fireworks/routers/glm-5p2-fast \
      --thinking high \
      --session-id "${sessid}" \
      --message "${prompt}" >>"${log_file}" 2>&1; then
      echo "news: ${source_id} ok (log: ${log_file})"
      return 0
    else
      local status=$?
      echo "news: ${source_id} failed (status ${status}, log: ${log_file})"
      write_collection_error \
        "${source_id}" "${source_name}" "${url}" "${sessid}" "${status}" "${log_file}"
      return "${status}"
    fi
  }

  # Read news-sources.json and spawn agents
  if [[ -f "${NEWS_SOURCES}" ]]; then
    while IFS= read -r entry; do
      source_id=$(echo "$entry" | jq -r '.id')
      source_name=$(echo "$entry" | jq -r '.name')
      url=$(echo "$entry" | jq -r '.url')
      access=$(echo "$entry" | jq -r '.access')
      collection_scope=$(echo "$entry" | jq -r '.collect // "Items relevant to a long-only investor."')

      if [[ "$access" == "browser" ]]; then
        echo "  spawning browser agent: ${source_id}"
        collect_source "${BROWSER_PROMPT_TEMPLATE}" 2400 \
          "$source_id" "$source_name" "$url" "$collection_scope" &
        PIDS+=($!)
      elif [[ "$access" == "web_fetch" ]]; then
        echo "  spawning web_fetch agent: ${source_id}"
        collect_source "${WEBFETCH_PROMPT_TEMPLATE}" 300 \
          "$source_id" "$source_name" "$url" "$collection_scope" &
        PIDS+=($!)
      fi
    done < <(jq -c '.[]' "${NEWS_SOURCES}")
  fi

  # Read ir-registry.json in configurable batches. This avoids a hard-coded
  # global browser ceiling while allowing operators to increase parallelism.
  if [[ -f "${IR_REGISTRY}" ]]; then
    IR_PIDS=()
    while IFS= read -r entry; do
      ticker=$(echo "$entry" | jq -r '.security_id')
      url=$(echo "$entry" | jq -r '.feeds[0].url // empty')

      if [[ -z "$url" ]]; then
        continue
      fi

      echo "  spawning IR browser agent: ${ticker}"
      collect_source "${BROWSER_PROMPT_TEMPLATE}" 2400 \
        "ir-${ticker}" "IR — ${ticker}" "$url" \
        "New investor-relations releases, filings, earnings materials, capital-allocation announcements, or other material company updates published within the last 3 days." &
      IR_PIDS+=($!)

      if [[ "${#IR_PIDS[@]}" -ge "${MINERVA_IR_BATCH_SIZE}" ]]; then
        echo "  waiting for IR batch (${#IR_PIDS[@]} collectors)..."
        for pid in "${IR_PIDS[@]}"; do
          wait "$pid" 2>/dev/null || true
        done
        IR_PIDS=()
      fi
    done < <(jq -c '.[]' "${IR_REGISTRY}")

    if [[ "${#IR_PIDS[@]}" -gt 0 ]]; then
      for pid in "${IR_PIDS[@]}"; do
        wait "$pid" 2>/dev/null || true
      done
    fi
  fi

  # Wait for all collectors.
  echo "  waiting for news agents..."
  if [[ "${#PIDS[@]}" -gt 0 ]]; then
    for pid in "${PIDS[@]}"; do
      wait "$pid" 2>/dev/null || true
    done
  fi

  COLLECTION_ERROR_COUNT=$(find "${NEWS_DIR}/raw" -name "*-error.md" 2>/dev/null | wc -l | tr -d ' ')
  if [[ "${COLLECTION_ERROR_COUNT}" -gt 0 ]]; then
    echo "  news collection completed with ${COLLECTION_ERROR_COUNT} collector error(s); logs: ${NEWS_LOG_DIR}"
  else
    echo "  news collection complete; logs: ${NEWS_LOG_DIR}"
  fi
fi

echo ""

# ── PHASE 2b: Summarize raw articles with extract-files ──
echo "── Phase 2b: Summarize articles ──"

RAW_COUNT=$(find "${NEWS_DIR}/raw" -name "*.md" -not -name "*-error.md" 2>/dev/null | wc -l | tr -d ' ')
if [[ "${RAW_COUNT}" -gt 0 ]]; then
  EXTRACT_PROMPT="Summarize this article for a long-only investor in one detailed paragraph. Include: the key facts, why it matters for markets or specific companies, and any portfolio implications. If the article is a press release or data release, focus on the numbers and what they signal. Be specific — name companies, figures, and dates."

  run extract-files \
    -f "${NEWS_DIR}/raw/*.md" \
    -o "${NEWS_DIR}/summaries" \
    --model gemini-3.6-flash \
    --thinking high \
    --concurrency 4 \
    --force \
    "${EXTRACT_PROMPT}" || echo "extract-files: failed (non-fatal)"

  echo "  summarized ${RAW_COUNT} articles"
else
  echo "  no raw articles to summarize"
fi

echo ""

# ── PHASE 2c: Ingest raw + summaries into invest.db ──
# One writer, single SQLite transaction. Parallel collectors only perform
# read-only existence checks; they produce markdown into NEWS_RUN_DIR.
echo "── Phase 2c: Ingest into invest.db ──"

ingest_report="${NEWS_RUN_DIR}/logs/ingest.log"
ingest_stats="${NEWS_RUN_DIR}/logs/ingest.json"
if [[ "${RAW_COUNT}" -gt 0 ]]; then
  if run news ingest \
      --raw-dir "${NEWS_RUN_DIR}/raw" \
      --summaries-dir "${NEWS_RUN_DIR}/summaries" \
      --db "${INVEST_DB}" \
      --news-sources "${NEWS_SOURCES}" \
      --ir-registry "${IR_REGISTRY}" \
      --report "${ingest_report}" > "${ingest_stats}"; then
    INGEST_OK=1
    echo "  ingest stats: $(cat "${ingest_stats}")"
  else
    echo "news ingest: failed (temp run dir preserved at ${NEWS_RUN_DIR})" >&2
    exit 1
  fi
else
  # Nothing to ingest, but the temp dir is safe to remove.
  echo '{"eligible": 0}' > "${ingest_stats}"
  INGEST_OK=1
fi

echo ""

if [[ "${MINERVA_SKIP_NEWS}" != "1" && "${MINERVA_ALLOW_THIN_BRIEF}" != "1" ]]; then
  eligible_count=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("eligible", 0))' "${ingest_stats}" 2>/dev/null || echo 0)
  if [[ "${eligible_count}" -eq 0 ]]; then
    echo "news: no eligible articles were ingested" >&2
    echo "news: refusing to continue without article evidence; set MINERVA_ALLOW_THIN_BRIEF=1 to allow a thin brief" >&2
    echo "news: temp run directory preserved at ${NEWS_RUN_DIR}" >&2
    INGEST_OK=0
    exit 1
  fi
fi

echo ""

# ── PHASE 4: Evidence preparation ──
echo "── Phase 4: Evidence preparation ──"

run brief prep --date "${RUN_DATE}"

# Manifest check (relaxed: macro and ir no longer required)
MANIFEST_PATH="${REPORT_DIR}/data/raw/manifest.json"

if [[ "${MINERVA_SKIP_STATUS_CHECK}" != "1" ]]; then
  uv run python - "${MANIFEST_PATH}" <<'PY'
import json
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
sources = manifest.get("sources", {})
required = ["filings", "earnings", "market", "prep"]
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

echo ""

# ── Output paths ──
PREPARED_PATH="${REPORT_DIR}/data/structured/prepared-evidence.json"
echo "prepared_evidence: ${PREPARED_PATH}"
echo "manifest: ${MANIFEST_PATH}"
echo "news_db: ${INVEST_DB}"
echo "main_agent_step: read prepared evidence + query today's fresh rows from the news table (published_at is Unix UTC seconds; use datetime(published_at, 'unixepoch') for display), then write notes/morning-brief-report.md and notes/slack-brief.md"
