#!/usr/bin/env bash

# Source env for API keys BEFORE strict mode
# zshrc contains zsh-specific commands (setopt) that fail in bash with set -e
source ~/.zshrc >/dev/null 2>&1 || true

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.."; pwd)"
RUN_DATE="${1:-$(date +%F)}"
NEWS_DIR="${ROOT_DIR}/hard-disk/data/02-news/${RUN_DATE}"
REPORT_DIR="${ROOT_DIR}/hard-disk/reports/03-daily-news/${RUN_DATE}"

export UV_CACHE_DIR="${UV_CACHE_DIR:-${ROOT_DIR}/.uv-cache}"
export MINERVA_WORKSPACE_ROOT="${MINERVA_WORKSPACE_ROOT:-${ROOT_DIR}/hard-disk}"

MINERVA_RUNNER="${MINERVA_RUNNER:-uv run minerva}"
MINERVA_BRIEF_EARNINGS_PROVIDER="${MINERVA_BRIEF_EARNINGS_PROVIDER:-finnhub}"
MINERVA_BRIEF_MARKET_PROVIDER="${MINERVA_BRIEF_MARKET_PROVIDER:-finnhub}"
MINERVA_SKIP_STATUS_CHECK="${MINERVA_SKIP_STATUS_CHECK:-0}"
MINERVA_SKIP_NEWS="${MINERVA_SKIP_NEWS:-0}"

IFS=' ' read -r -a MINERVA_RUNNER_ARR <<< "${MINERVA_RUNNER}"

run() { "${MINERVA_RUNNER_ARR[@]}" "$@"; }

mkdir -p "${REPORT_DIR}" "${NEWS_DIR}/raw" "${NEWS_DIR}/summaries"

echo "=== Morning Brief Pipeline ==="
echo "date: ${RUN_DATE}"
echo "news_dir: ${NEWS_DIR}"
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
  NEWS_BASE="${ROOT_DIR}/hard-disk/data/02-news"
  PIDS=()

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

  # ── Build dedup slug list from last 3 days ──
  DEDUP_SLUGS=""
  for days_ago in 1 2 3; do
    prev_date=$(date -v-${days_ago}d +%F 2>/dev/null || date -d "${RUN_DATE} -${days_ago} days" +%F 2>/dev/null || true)
    prev_dir="${NEWS_BASE}/${prev_date}/raw"
    if [[ -d "$prev_dir" ]]; then
      # Extract slugs: filename minus source prefix and .md extension
      # e.g. wsj-trump-hormuz-ships.md → trump-hormuz-ships
      for f in "$prev_dir"/*.md; do
        [[ -f "$f" ]] || continue
        bn=$(basename "$f" .md)
        # Strip source prefix (everything up to and including the first hyphen-separated source id)
        slug=$(echo "$bn" | sed -E 's/^(wsj|economist|reuters-markets|bls-calendar|bea-schedule|fed-press|ir-[A-Z0-9]+)-//')
        DEDUP_SLUGS="${DEDUP_SLUGS}${slug}\n"
      done
    fi
  done

  # Also include today's raw dir (in case of re-run)
  if [[ -d "${NEWS_DIR}/raw" ]]; then
    for f in "${NEWS_DIR}/raw"/*.md; do
      [[ -f "$f" ]] || continue
      bn=$(basename "$f" .md)
      slug=$(echo "$bn" | sed -E 's/^(wsj|economist|reuters-markets|bls-calendar|bea-schedule|fed-press|ir-[A-Z0-9]+)-//')
      DEDUP_SLUGS="${DEDUP_SLUGS}${slug}\n"
    done
  fi

  # Deduplicate, sort, and write to temp file
  DEDUP_FILE=$(mktemp)
  trap "rm -f '$DEDUP_FILE'" EXIT
  if [[ -n "$DEDUP_SLUGS" ]]; then
    echo -e "$DEDUP_SLUGS" | sort -u | grep -v '^$' > "$DEDUP_FILE" || true
    dedup_count=$(wc -l < "$DEDUP_FILE" | tr -d ' ')
    echo "  dedup list: ${dedup_count} slugs from recent days"
  else
    echo "(none)" > "$DEDUP_FILE"
    echo "  dedup list: empty (first run)"
  fi

  # Helper: spawn one browser-based collection agent
  collect_browser() {
    local source_id="$1" source_name="$2" url="$3"
    local sessid="news-${source_id}-$(date +%s)"
    local prompt
    prompt=$(sed \
      -e "s|{{DATE}}|${RUN_DATE}|g" \
      -e "s|{{SOURCE_NAME}}|${source_name}|g" \
      -e "s|{{SOURCE_ID}}|${source_id}|g" \
      -e "s|{{URL}}|${url}|g" \
      -e "s|{{NEWS_DIR}}|${NEWS_DIR}|g" \
      "${BROWSER_PROMPT_TEMPLATE}")

    # Inject dedup slugs from temp file
    local dedup_content
    dedup_content=$(cat "$DEDUP_FILE")
    prompt=$(python3 -c "import sys; t=sys.stdin.read(); t=t.replace('{{DEDUP_SLUGS}}', sys.argv[1]); t=t.replace('{{PORTFOLIO_TICKERS}}', sys.argv[2]); print(t)" "$dedup_content" "$PORTFOLIO_TICKERS" <<< "$prompt")

    openclaw agent \
      --agent main \
      --timeout 2400 \
      --thinking medium \
      --session-id "${sessid}" \
      --message "${prompt}" >/dev/null 2>&1 || echo "news: ${source_id} failed"
  }

  # Helper: spawn one web_fetch-based collection agent
  collect_webfetch() {
    local source_id="$1" source_name="$2" url="$3"
    local sessid="news-${source_id}-$(date +%s)"
    local prompt
    prompt=$(sed \
      -e "s|{{DATE}}|${RUN_DATE}|g" \
      -e "s|{{SOURCE_NAME}}|${source_name}|g" \
      -e "s|{{SOURCE_ID}}|${source_id}|g" \
      -e "s|{{URL}}|${url}|g" \
      -e "s|{{NEWS_DIR}}|${NEWS_DIR}|g" \
      "${WEBFETCH_PROMPT_TEMPLATE}")

    # Inject dedup slugs from temp file
    local dedup_content
    dedup_content=$(cat "$DEDUP_FILE")
    prompt=$(python3 -c "import sys; t=sys.stdin.read(); t=t.replace('{{DEDUP_SLUGS}}', sys.argv[1]); t=t.replace('{{PORTFOLIO_TICKERS}}', sys.argv[2]); print(t)" "$dedup_content" "$PORTFOLIO_TICKERS" <<< "$prompt")

    openclaw agent \
      --agent main \
      --timeout 300 \
      --thinking medium \
      --session-id "${sessid}" \
      --message "${prompt}" >/dev/null 2>&1 || echo "news: ${source_id} failed"
  }

  # Read news-sources.json and spawn agents
  if [[ -f "${NEWS_SOURCES}" ]]; then
    while IFS= read -r entry; do
      source_id=$(echo "$entry" | jq -r '.id')
      source_name=$(echo "$entry" | jq -r '.name')
      url=$(echo "$entry" | jq -r '.url')
      access=$(echo "$entry" | jq -r '.access')

      if [[ "$access" == "browser" ]]; then
        echo "  spawning browser agent: ${source_id}"
        collect_browser "$source_id" "$source_name" "$url" &
        PIDS+=($!)
      elif [[ "$access" == "web_fetch" ]]; then
        echo "  spawning web_fetch agent: ${source_id}"
        collect_webfetch "$source_id" "$source_name" "$url" &
        PIDS+=($!)
      fi
    done < <(jq -c '.[]' "${NEWS_SOURCES}")
  fi

  # Read ir-registry.json and spawn browser agents (batched in groups of 5)
  if [[ -f "${IR_REGISTRY}" ]]; then
    IR_BATCH_SIZE=5
    IR_COUNT=0
    IR_PIDS=()

    while IFS= read -r entry; do
      ticker=$(echo "$entry" | jq -r '.security_id')
      company=$(echo "$entry" | jq -r '.company_name')
      url=$(echo "$entry" | jq -r '.feeds[0].url // empty')

      if [[ -z "$url" ]]; then
        continue
      fi

      echo "  spawning IR browser agent: ${ticker}"
      collect_browser "ir-${ticker}" "IR — ${ticker}" "$url" &
      IR_PIDS+=($!)
      IR_COUNT=$((IR_COUNT + 1))

      # Wait for batch to complete
      if [[ $((IR_COUNT % IR_BATCH_SIZE)) -eq 0 ]]; then
        echo "  waiting for IR batch..."
        for pid in "${IR_PIDS[@]}"; do
          wait "$pid" 2>/dev/null || true
        done
        IR_PIDS=()
      fi
    done < <(jq -c '.[]' "${IR_REGISTRY}")

    # Wait for remaining IR agents
    for pid in "${IR_PIDS[@]}"; do
      wait "$pid" 2>/dev/null || true
    done
  fi

  # Wait for all editorial/calendar agents
  echo "  waiting for news agents..."
  for pid in "${PIDS[@]}"; do
    wait "$pid" 2>/dev/null || true
  done

  echo "  news collection complete"
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
    --model gemini-3-flash \
    --concurrency 4 \
    --force \
    "${EXTRACT_PROMPT}" || echo "extract-files: failed (non-fatal)"

  echo "  summarized ${RAW_COUNT} articles"
else
  echo "  no raw articles to summarize"
fi

echo ""

# ── PHASE 3: Merge summaries → per-source summaries + articles.md + INDEX.md ──
echo "── Phase 3: Merge ──"

MERGE_SCRIPT="${ROOT_DIR}/scripts/merge_news.py"
if [[ ! -f "${MERGE_SCRIPT}" ]]; then
  echo "merge_news: script not found at ${MERGE_SCRIPT}, skipping"
else
  uv run python "${MERGE_SCRIPT}" \
    --raw-dir "${NEWS_DIR}/raw" \
    --summaries-dir "${NEWS_DIR}/summaries" \
    --date-dir "${NEWS_DIR}" \
    --ledger "${ROOT_DIR}/hard-disk/data/02-news/LEDGER.md" \
    --date "${RUN_DATE}" || echo "merge_news: failed (non-fatal)"
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
echo "articles: ${NEWS_DIR}/articles.md"
echo "main_agent_step: read prepared evidence + articles.md, write notes/morning-brief-report.md and notes/slack-brief.md"
