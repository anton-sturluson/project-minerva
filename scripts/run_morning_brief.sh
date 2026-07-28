#!/usr/bin/env bash

# Source API keys before strict mode, but preserve the caller's exported
# environment as the higher-precedence configuration layer. zshrc may contain
# zsh-only commands, so a non-zero result is intentionally ignored.
_CALLER_ENV_EXPORTS="$(export -p)"
source ~/.zshrc >/dev/null 2>&1 || true
eval "${_CALLER_ENV_EXPORTS}"
unset _CALLER_ENV_EXPORTS

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.."; pwd)"
HELPER="${ROOT_DIR}/scripts/morning_brief_helper.py"
RUN_DATE="${1:-$(date +%F)}"
MINERVA_BROWSER_TIMEOUT="${MINERVA_BROWSER_TIMEOUT:-900}"
MINERVA_WEBFETCH_TIMEOUT="${MINERVA_WEBFETCH_TIMEOUT:-300}"
MINERVA_MAX_COLLECTORS="${MINERVA_MAX_COLLECTORS:-8}"
MINERVA_NEWS_COLLECTOR_AGENT="${MINERVA_NEWS_COLLECTOR_AGENT:-steve}"
for integer_name in \
  MINERVA_BROWSER_TIMEOUT \
  MINERVA_WEBFETCH_TIMEOUT \
  MINERVA_MAX_COLLECTORS; do
  integer_value="${!integer_name}"
  if ! [[ "${integer_value}" =~ ^[1-9][0-9]*$ ]]; then
    echo "${integer_name} must be a positive integer" >&2
    exit 1
  fi
done
if ! PREVIOUS_DATE="$(python3 "${HELPER}" previous-date "${RUN_DATE}")"; then
  exit 1
fi

export UV_CACHE_DIR="${UV_CACHE_DIR:-${ROOT_DIR}/.uv-cache}"
export MINERVA_WORKSPACE_ROOT="${MINERVA_WORKSPACE_ROOT:-${ROOT_DIR}/hard-disk}"

REPORT_DIR="${MINERVA_REPORT_DIR:-${MINERVA_WORKSPACE_ROOT}/reports/03-daily-news/${RUN_DATE}}"
INVEST_DB="${INVEST_DB:-${MINERVA_WORKSPACE_ROOT}/data/04-database/invest.db}"
PHASE_DIR="${MINERVA_NEWS_ARTIFACT_DIR:-${REPORT_DIR}/data/structured/news-pipeline}"
COLLECTOR_ARTIFACT_DIR="${PHASE_DIR}/collectors"
NEWS_RUN_DIR="$(mktemp -d "${TMPDIR:-/tmp}/morning-brief-${RUN_DATE}-XXXXXX")"
NEWS_SOURCE_ROOTS_DIR="${NEWS_RUN_DIR}/sources"
cleanup_run_dir() {
  # Candidate and lookup metadata is ephemeral. Collector responses are never
  # retained because they could accidentally contain article body text.
  rm -rf "${NEWS_RUN_DIR}"
}
trap cleanup_run_dir EXIT

MINERVA_RUNNER="${MINERVA_RUNNER:-uv run minerva}"
MINERVA_BRIEF_EARNINGS_PROVIDER="${MINERVA_BRIEF_EARNINGS_PROVIDER:-finnhub}"
MINERVA_BRIEF_MARKET_PROVIDER="${MINERVA_BRIEF_MARKET_PROVIDER:-finnhub}"
MINERVA_SKIP_STATUS_CHECK="${MINERVA_SKIP_STATUS_CHECK:-0}"
MINERVA_SKIP_NEWS="${MINERVA_SKIP_NEWS:-0}"
MINERVA_ALLOW_THIN_BRIEF="${MINERVA_ALLOW_THIN_BRIEF:-0}"

IFS=' ' read -r -a MINERVA_RUNNER_ARR <<< "${MINERVA_RUNNER}"
run() { "${MINERVA_RUNNER_ARR[@]}" "$@"; }

# Collector agents may run from another OpenClaw workspace. Render shell-quoted,
# repository-anchored commands so they always use this checkout and this DB.
printf -v NEWS_EXIST_RUNNER '%q ' "${MINERVA_RUNNER_ARR[@]}" news exist
NEWS_EXIST_RUNNER="${NEWS_EXIST_RUNNER% }"
printf -v NEWS_EXIST_COMMAND 'cd %q && %s' "${ROOT_DIR}" "${NEWS_EXIST_RUNNER}"
printf -v NEWS_INGEST_RUNNER '%q ' \
  "${MINERVA_RUNNER_ARR[@]}" news ingest --input - --db "${INVEST_DB}"
NEWS_INGEST_RUNNER="${NEWS_INGEST_RUNNER% }"
printf -v NEWS_INGEST_COMMAND '(cd %q && %s)' \
  "${ROOT_DIR}" "${NEWS_INGEST_RUNNER}"

mkdir -p "${REPORT_DIR}" "${PHASE_DIR}" "${COLLECTOR_ARTIFACT_DIR}" \
  "${NEWS_SOURCE_ROOTS_DIR}"

write_status() {
  local destination="$1" phase="$2" status="$3" exit_status="$4"
  local stdout_path="${5:-}" stderr_path="${6:-}"
  python3 "${HELPER}" write-status \
    "${destination}" "${phase}" "${status}" "${exit_status}" \
    "${stdout_path}" "${stderr_path}"
}

run_minerva_phase() {
  local phase="$1"
  shift
  local stdout_path="${PHASE_DIR}/${phase}.json"
  local stderr_path="${PHASE_DIR}/${phase}.stderr.log"
  local status
  if run "$@" >"${stdout_path}" 2>"${stderr_path}"; then
    write_status "${PHASE_DIR}/${phase}.status.json" "${phase}" ok 0 \
      "${stdout_path}" "${stderr_path}"
    if [[ -s "${stdout_path}" ]]; then
      echo "  ${phase}: $(tail -n 1 "${stdout_path}")"
    else
      echo "  ${phase}: ok"
    fi
  else
    status=$?
    write_status "${PHASE_DIR}/${phase}.status.json" "${phase}" failed \
      "${status}" "${stdout_path}" "${stderr_path}"
    echo "error[${phase}]: failed with status ${status}" >&2
    echo "error[${phase}]: diagnostics: ${stderr_path}" >&2
    [[ ! -s "${stderr_path}" ]] || tail -n 20 "${stderr_path}" >&2
    return "${status}"
  fi
}

echo "=== Morning Brief Pipeline ==="
echo "date: ${RUN_DATE}"
echo "news_run_dir: ${NEWS_RUN_DIR}"
echo "invest_db: ${INVEST_DB}"
echo "report_dir: ${REPORT_DIR}"
echo "phase_artifacts: ${PHASE_DIR}"
echo ""

# ── PHASE 1: Structured data collection ──
echo "── Phase 1: Structured data ──"

portfolio_sync_args=(portfolio sync --date "${RUN_DATE}")
[[ -n "${MINERVA_PORTFOLIO_HOLDINGS_SOURCE:-}" ]] && portfolio_sync_args+=(--holdings-source "${MINERVA_PORTFOLIO_HOLDINGS_SOURCE}")
[[ -n "${MINERVA_PORTFOLIO_TRANSACTIONS_SOURCE:-}" ]] && portfolio_sync_args+=(--transactions-source "${MINERVA_PORTFOLIO_TRANSACTIONS_SOURCE}")
[[ -n "${MINERVA_PORTFOLIO_WATCHLIST_SOURCE:-}" ]] && portfolio_sync_args+=(--watchlist-source "${MINERVA_PORTFOLIO_WATCHLIST_SOURCE}")
run_minerva_phase portfolio-sync "${portfolio_sync_args[@]}"

run_minerva_phase filings brief filings --date "${RUN_DATE}"

earnings_args=(brief earnings --date "${RUN_DATE}" --provider "${MINERVA_BRIEF_EARNINGS_PROVIDER}")
[[ -n "${MINERVA_BRIEF_EARNINGS_SOURCE:-}" ]] && earnings_args+=(--source "${MINERVA_BRIEF_EARNINGS_SOURCE}")
run_minerva_phase earnings "${earnings_args[@]}"

market_args=(brief market --date "${RUN_DATE}" --provider "${MINERVA_BRIEF_MARKET_PROVIDER}")
[[ -n "${MINERVA_BRIEF_MARKET_SOURCE:-}" ]] && market_args+=(--source "${MINERVA_BRIEF_MARKET_SOURCE}")
run_minerva_phase market "${market_args[@]}"

echo ""

if [[ "${MINERVA_SKIP_NEWS}" == "1" ]]; then
  echo "── Phase 2: News collection (skipped) ──"
  write_status "${PHASE_DIR}/news.status.json" news skipped 0
  python3 "${HELPER}" window-evidence \
    "${INVEST_DB}" "${RUN_DATE}" "${PHASE_DIR}/window-evidence.json" \
    --skipped
else
  # ── PHASE 2a: Direct aggregate downloads ──
  echo "── Phase 2a: Direct Finnhub and market downloads ──"
  # Fetch both publication dates that intersect the fixed 04:00-to-04:00
  # window. Direct ingestion deduplicates overlapping provider results.
  run_minerva_phase finnhub-news-previous news download-finnhub \
    --date "${PREVIOUS_DATE}" --db "${INVEST_DB}"
  run_minerva_phase finnhub-news news download-finnhub \
    --date "${RUN_DATE}" --db "${INVEST_DB}"
  # With no --index/--symbol overrides, market data uses default indexes plus
  # the current holdings + watchlist universe.
  run_minerva_phase market-data news download-market-data \
    --date "${RUN_DATE}" --db "${INVEST_DB}"

  # ── PHASE 2b: Direct-ingest browser/web_fetch collectors ──
  echo ""
  echo "── Phase 2b: Direct-ingest collectors ──"

  BROWSER_PROMPT_TEMPLATE="${ROOT_DIR}/scripts/prompts/collect_news.md"
  WEBFETCH_PROMPT_TEMPLATE="${ROOT_DIR}/scripts/prompts/collect_news_webfetch.md"
  IR_BATCH_PROMPT_TEMPLATE="${ROOT_DIR}/scripts/prompts/collect_ir_batch.md"
  NEWS_SOURCES="${MINERVA_NEWS_SOURCES:-${MINERVA_WORKSPACE_ROOT}/data/02-news/news-sources.json}"
  PORTFOLIO_UNIVERSE="${MINERVA_PORTFOLIO_UNIVERSE:-${MINERVA_WORKSPACE_ROOT}/data/01-portfolio/current/universe.json}"
  IR_REGISTRY="${MINERVA_IR_REGISTRY:-${MINERVA_WORKSPACE_ROOT}/data/01-portfolio/current/ir-registry.json}"
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
    echo "error[collectors]: malformed source registry: ${NEWS_SOURCES}" >&2
    exit 1
  fi
  if [[ -f "${PORTFOLIO_UNIVERSE}" ]] && ! jq -e '
    type == "array" and all(.[];
      type == "object" and
      (.security_id | type == "string" and length > 0)
    )
  ' "${PORTFOLIO_UNIVERSE}" >/dev/null; then
    echo "error[collectors]: malformed portfolio universe: ${PORTFOLIO_UNIVERSE}" >&2
    exit 1
  fi
  if [[ -f "${IR_REGISTRY}" ]] && ! jq -e '
    type == "array" and all(.[];
      type == "object" and
      (.security_id | type == "string" and length > 0) and
      (.feeds | type == "array") and
      all(.feeds[]; type == "object" and (.url | type == "string" and length > 0))
    )
  ' "${IR_REGISTRY}" >/dev/null; then
    echo "error[collectors]: malformed IR registry: ${IR_REGISTRY}" >&2
    exit 1
  fi

  # Build portfolio company context for relevance ranking in collector prompts.
  COMPANY_DIR="${MINERVA_WORKSPACE_ROOT}/data/01-portfolio/current/company-directory.md"
  RENDERED_PORTFOLIO="${MINERVA_WORKSPACE_ROOT}/data/01-portfolio/current/rendered.md"
  PORTFOLIO_TICKERS="(not available)"
  if [[ -f "${RENDERED_PORTFOLIO}" ]]; then
    active_tickers=$(grep -E '^- `[A-Z0-9.]+`' "${RENDERED_PORTFOLIO}" | sed 's/- `\([^`]*\)`.*/\1/' | sort -u || true)
    PORTFOLIO_TICKERS=""
    while read -r tkr; do
      [[ -n "${tkr}" ]] || continue
      name=""
      if [[ -f "${COMPANY_DIR}" ]]; then
        name=$(grep -E "^\| ${tkr} \|" "${COMPANY_DIR}" 2>/dev/null | head -1 | awk -F'|' '{gsub(/^ +| +$/, "", $3); print $3}' || true)
      fi
      entry="${name:-${tkr}}"
      PORTFOLIO_TICKERS="${PORTFOLIO_TICKERS:+${PORTFOLIO_TICKERS}, }${entry}"
    done <<< "${active_tickers}"
    PORTFOLIO_TICKERS="${PORTFOLIO_TICKERS:-(not available)}"
    echo "  portfolio: ${PORTFOLIO_TICKERS}"
  fi

  render_collection_prompt() {
    local template="$1" source_name="$2" source_id="$3" url="$4"
    local collection_scope="$5" source_root="$6"
    python3 "${HELPER}" render-prompt \
      "${template}" "${RUN_DATE}" "${source_name}" "${source_id}" \
      "${url}" "${source_root}" "${INVEST_DB}" \
      "${NEWS_EXIST_COMMAND}" "${NEWS_INGEST_COMMAND}" \
      "${PORTFOLIO_TICKERS}" "${collection_scope}" \
      "${source_root}/candidates.json" "${source_root}/lookup.json"
  }

  write_collector_status() {
    local destination="$1" source_id="$2" source_name="$3" url="$4"
    local session_id="$5" status="$6" exit_status="$7" log_file="$8"
    local output_bytes="$9"
    python3 "${HELPER}" collector-status \
      "${destination}" "${source_id}" "${source_name}" "${url}" \
      "${session_id}" "${status}" "${exit_status}" "${log_file}" \
      "${output_bytes}"
  }

  collect_source() {
    local prompt_template="$1" timeout="$2" source_id="$3" source_name="$4"
    local url="$5" collection_scope="$6" source_root="$7"
    local artifact_root="${COLLECTOR_ARTIFACT_DIR}/${source_id}"
    local session_id="news-${source_id}-${RUN_DATE}-$$-${RANDOM}"
    local lifecycle_log="${artifact_root}/collector.log"
    local status_file="${artifact_root}/status.json"
    local prompt exit_status output_bytes result_status
    mkdir -p "${artifact_root}"
    prompt=$(render_collection_prompt "${prompt_template}" "${source_name}" \
      "${source_id}" "${url}" "${collection_scope}" "${source_root}")

    {
      echo "source_id: ${source_id}"
      echo "source_name: ${source_name}"
      echo "url: ${url}"
      echo "session_id: ${session_id}"
      echo "started_at: $(date -u +%FT%TZ)"
    } >"${lifecycle_log}"

    # Count and discard agent output as a stream. Even if an agent violates the
    # reply contract, an article body is never materialized in a temp file.
    if output_bytes=$(openclaw agent \
      --agent "${MINERVA_NEWS_COLLECTOR_AGENT}" \
      --timeout "${timeout}" \
      --model fireworks/accounts/fireworks/routers/glm-5p2-fast \
      --thinking high \
      --session-id "${session_id}" \
      --message "${prompt}" 2>&1 | wc -c); then
      exit_status=0
      result_status=ok
    else
      exit_status=$?
      result_status=failed
    fi
    output_bytes=$(echo "${output_bytes}" | tr -d ' ')
    {
      echo "finished_at: $(date -u +%FT%TZ)"
      echo "status: ${result_status}"
      echo "exit_status: ${exit_status}"
      echo "openclaw_output_bytes: ${output_bytes}"
      echo "note: OpenClaw output discarded to prevent article-body persistence"
    } >>"${lifecycle_log}"
    write_collector_status "${status_file}" "${source_id}" "${source_name}" \
      "${url}" "${session_id}" "${result_status}" "${exit_status}" \
      "${lifecycle_log}" "${output_bytes}"

    if [[ "${exit_status}" -eq 0 ]]; then
      echo "news: ${source_id} ok (status: ${status_file})"
    else
      echo "news: ${source_id} failed (status ${exit_status}; status: ${status_file})"
    fi
    return "${exit_status}"
  }

  wait_for_collectors() {
    if [[ "${#PIDS[@]}" -eq 0 ]]; then
      return 0
    fi
    echo "  waiting for collector batch (${#PIDS[@]} agents)..."
    for pid in "${PIDS[@]}"; do
      wait "${pid}" 2>/dev/null || true
    done
    PIDS=()
  }

  launch_source() {
    local prompt_template="$1" timeout="$2" source_id="$3" source_name="$4"
    local url="$5" collection_scope="$6"
    if ! [[ "${source_id}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
      echo "error[collectors]: unsafe source id: ${source_id}" >&2
      return 1
    fi
    local source_root="${NEWS_SOURCE_ROOTS_DIR}/${source_id}"
    if [[ -e "${source_root}" ]]; then
      echo "error[collectors]: duplicate source id: ${source_id}" >&2
      return 1
    fi
    mkdir -p "${source_root}"
    printf '%s\n' "${source_id}" >>"${NEWS_RUN_DIR}/launched.txt"
    collect_source "${prompt_template}" "${timeout}" "${source_id}" \
      "${source_name}" "${url}" "${collection_scope}" "${source_root}" &
    PIDS+=("$!")
    if [[ "${#PIDS[@]}" -ge "${MINERVA_MAX_COLLECTORS}" ]]; then
      wait_for_collectors
    fi
  }

  # The daily workflow has exactly three editorial collector slots. Official
  # macro sources are handled by structured phases, not news-agent sessions.
  if [[ -f "${NEWS_SOURCES}" ]]; then
    for editorial_id in wsj economist reuters-markets; do
      entry=$(jq -c --arg id "${editorial_id}" \
        'map(select(.id == $id)) | first // empty' "${NEWS_SOURCES}")
      [[ -n "${entry}" ]] || continue
      source_id=$(echo "${entry}" | jq -r '.id')
      source_name=$(echo "${entry}" | jq -r '.name')
      url=$(echo "${entry}" | jq -r '.url')
      access=$(echo "${entry}" | jq -r '.access')
      collection_scope=$(echo "${entry}" | jq -r '.collect // "Items relevant to a long-only investor."')
      if [[ "${access}" == "browser" ]]; then
        echo "  spawning browser agent: ${source_id}"
        launch_source "${BROWSER_PROMPT_TEMPLATE}" "${MINERVA_BROWSER_TIMEOUT}" \
          "${source_id}" "${source_name}" "${url}" "${collection_scope}"
      else
        echo "  spawning web_fetch agent: ${source_id}"
        launch_source "${WEBFETCH_PROMPT_TEMPLATE}" "${MINERVA_WEBFETCH_TIMEOUT}" \
          "${source_id}" "${source_name}" "${url}" "${collection_scope}"
      fi
    done
  fi

  # IR registry rows are metadata only. Select current-universe companies with
  # configured feeds, sort by security_id, then chunk into sessions of ten.
  if [[ -f "${PORTFOLIO_UNIVERSE}" && -f "${IR_REGISTRY}" ]]; then
    python3 "${HELPER}" ir-batches \
      "${PORTFOLIO_UNIVERSE}" "${IR_REGISTRY}" \
      >"${NEWS_RUN_DIR}/ir-batches.jsonl"
    ir_batch_number=0
    while IFS= read -r ir_companies_json; do
      [[ -n "${ir_companies_json}" ]] || continue
      ir_batch_number=$((ir_batch_number + 1))
      printf -v ir_batch_id 'ir-batch-%03d' "${ir_batch_number}"
      company_count=$(echo "${ir_companies_json}" | jq 'length')
      first_url=$(echo "${ir_companies_json}" | jq -r '.[0].feeds[0].url')
      echo "  spawning IR browser agent: ${ir_batch_id} (${company_count} companies)"
      launch_source "${IR_BATCH_PROMPT_TEMPLATE}" "${MINERVA_BROWSER_TIMEOUT}" \
        "${ir_batch_id}" "IR batch ${ir_batch_number}" "${first_url}" \
        "${ir_companies_json}"
    done <"${NEWS_RUN_DIR}/ir-batches.jsonl"
  fi

  echo "  waiting for news agents..."
  wait_for_collectors

  python3 "${HELPER}" collector-summary \
    "${NEWS_RUN_DIR}/launched.txt" "${COLLECTOR_ARTIFACT_DIR}" \
    "${PHASE_DIR}/collectors.json"
  COLLECTION_ERROR_COUNT=$(jq -r '.failed' "${PHASE_DIR}/collectors.json")
  if [[ "${COLLECTION_ERROR_COUNT}" -gt 0 ]]; then
    echo "  news collection completed with ${COLLECTION_ERROR_COUNT} collector error(s)"
    echo "  collector diagnostics: ${PHASE_DIR}/collectors.json"
  else
    echo "  news collection complete: $(cat "${PHASE_DIR}/collectors.json")"
  fi

  # ── PHASE 3: Fixed 04:00 America/New_York evidence gate ──
  echo ""
  echo "── Phase 3: Fixed 04:00 evidence gate ──"
  if python3 "${HELPER}" window-evidence \
      "${INVEST_DB}" "${RUN_DATE}" "${PHASE_DIR}/window-evidence.json" \
      2>"${PHASE_DIR}/window-evidence.stderr.log"
  then
    echo "  evidence: $(cat "${PHASE_DIR}/window-evidence.json")"
  else
    status=$?
    write_status "${PHASE_DIR}/window-evidence.status.json" \
      window-evidence failed "${status}" \
      "${PHASE_DIR}/window-evidence.json" \
      "${PHASE_DIR}/window-evidence.stderr.log"
    echo "error[window-evidence]: unable to inspect ${INVEST_DB}" >&2
    tail -n 20 "${PHASE_DIR}/window-evidence.stderr.log" >&2 || true
    exit "${status}"
  fi

  eligible_count=$(jq -r '.eligible_rows' "${PHASE_DIR}/window-evidence.json")
  if [[ "${eligible_count}" -eq 0 && "${MINERVA_ALLOW_THIN_BRIEF}" != "1" ]]; then
    echo "news: no eligible evidence exists in the fixed 04:00 New York window for ${RUN_DATE}" >&2
    echo "news: refusing a thin brief; set MINERVA_ALLOW_THIN_BRIEF=1 to override" >&2
    echo "news: evidence diagnostics: ${PHASE_DIR}/window-evidence.json" >&2
    exit 1
  fi
fi

echo ""

# ── PHASE 4: Evidence preparation ──
echo "── Phase 4: Evidence preparation ──"
run_minerva_phase prep brief prep --date "${RUN_DATE}"

MANIFEST_PATH="${REPORT_DIR}/data/raw/manifest.json"
if [[ "${MINERVA_SKIP_STATUS_CHECK}" != "1" ]]; then
  if python3 "${HELPER}" manifest-check "${MANIFEST_PATH}" \
      2>"${PHASE_DIR}/manifest-check.stderr.log"
  then
    write_status "${PHASE_DIR}/manifest-check.status.json" manifest-check ok 0
  else
    status=$?
    write_status "${PHASE_DIR}/manifest-check.status.json" manifest-check failed \
      "${status}" "" "${PHASE_DIR}/manifest-check.stderr.log"
    echo "error[manifest-check]: prepared evidence status check failed" >&2
    tail -n 20 "${PHASE_DIR}/manifest-check.stderr.log" >&2 || true
    exit "${status}"
  fi
else
  write_status "${PHASE_DIR}/manifest-check.status.json" manifest-check skipped 0
fi

PREPARED_PATH="${REPORT_DIR}/data/structured/prepared-evidence.json"
HANDOFF_PATH="${PHASE_DIR}/synthesis-handoff.json"
SYNTHESIS_PROMPT="${ROOT_DIR}/scripts/prompts/morning_brief_synthesis.md"
python3 "${HELPER}" write-handoff \
  "${HANDOFF_PATH}" "${RUN_DATE}" "${INVEST_DB}" "${PREPARED_PATH}" \
  "${REPORT_DIR}/notes/morning-brief-report.md" \
  "${REPORT_DIR}/notes/slack-brief.md" \
  "${PHASE_DIR}/window-evidence.json" "${SYNTHESIS_PROMPT}"

echo ""
echo "prepared_evidence: ${PREPARED_PATH}"
echo "manifest: ${MANIFEST_PATH}"
echo "news_db: ${INVEST_DB}"
echo "phase_artifacts: ${PHASE_DIR}"
echo "synthesis_handoff: ${HANDOFF_PATH}"
echo "synthesis_instructions: ${SYNTHESIS_PROMPT}"
echo "synthesis_step: Follow the versioned instructions to summarize rows in the fixed 04:00 New York window with NULL/blank summary, persist all summaries safely in one transaction, synthesize both report artifacts, and return the Slack brief for cron delivery. Do not post Slack from this script."
