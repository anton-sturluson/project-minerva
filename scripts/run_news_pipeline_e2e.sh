#!/usr/bin/env bash

# API keys used by the live providers and `minerva summarize` normally live in
# the operator's shell profile. Source it only when --live was explicitly
# requested; the safe default and stubbed tests must not execute profile code.
# Keep this before strict mode because .zshrc may contain zsh-only commands.
for e2e_arg in "$@"; do
  if [[ "${e2e_arg}" == "--live" ]]; then
    source ~/.zshrc >/dev/null 2>&1 || true
    break
  fi
done
unset e2e_arg

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.."; pwd)"
RUN_DATE="${MINERVA_E2E_DATE:-$(date +%F)}"
ARTICLE_URL="${MINERVA_E2E_ARTICLE_URL:-}"
SYMBOL="${MINERVA_E2E_SYMBOL:-NVDA}"
MARKET_INDEX="${MINERVA_E2E_INDEX:-^GSPC}"
COLLECTOR_AGENT="${MINERVA_E2E_COLLECTOR_AGENT:-main}"
COLLECTOR_MODEL="${MINERVA_E2E_COLLECTOR_MODEL:-fireworks/accounts/fireworks/routers/glm-5p2-fast}"
SOL_AGENT="${MINERVA_E2E_SOL_AGENT:-main}"
SOL_MODEL="${MINERVA_E2E_SOL_MODEL:-openai/gpt-5.6-sol}"
SUMMARY_MODEL="${MINERVA_E2E_SUMMARY_MODEL:-gemini-3.6-flash}"
AGENT_TIMEOUT="${MINERVA_E2E_AGENT_TIMEOUT:-900}"
RUN_ROOT="${MINERVA_E2E_RUN_ROOT:-${TMPDIR:-/tmp}/minerva-news-e2e-runs}"
OPENCLAW_COMMAND="${MINERVA_E2E_OPENCLAW:-openclaw}"
MINERVA_RUNNER="${MINERVA_RUNNER:-uv run minerva}"
MODE=""

usage() {
  cat <<'EOF'
Usage: scripts/run_news_pipeline_e2e.sh (--live | --stubbed) [options]

Runs the agent-driven news pipeline only against a newly created scratch DB.
The run directory is always preserved and Slack is never invoked.

Modes:
  --live                    Allow real OpenClaw, Finnhub, Yahoo, and LLM calls.
  --stubbed                 Require injected OpenClaw and Minerva test doubles.

Options:
  --date YYYY-MM-DD         Provider date (default: today).
  --article-url URL         One controlled public article URL (required).
  --symbol SYMBOL           Finnhub/Yahoo symbol (default: NVDA).
  --index SYMBOL            Yahoo index (default: ^GSPC).
  --collector-agent ID      Collector OpenClaw agent (default: main).
  --collector-model MODEL   Collector OpenClaw model.
  --sol-agent ID            Summarizer OpenClaw agent (default: main).
  --sol-model MODEL         Summarizer OpenClaw model (default: Sol).
  --summary-model MODEL     Model passed to `minerva summarize`.
  --run-root DIR            Parent for preserved run directories.
  -h, --help                Show this help.

Stubbed mode safety contract:
  Set MINERVA_E2E_OPENCLAW to a test double and MINERVA_RUNNER to a provider
  test double. The same production command arguments and prompts are built,
  but no real provider or agent is reachable accidentally.
EOF
}

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --live|--stubbed)
      if [[ -n "${MODE}" ]]; then
        echo "error: choose exactly one of --live or --stubbed" >&2
        exit 2
      fi
      MODE="${1#--}"
      shift
      ;;
    --date) RUN_DATE="${2:?--date requires a value}"; shift 2 ;;
    --article-url) ARTICLE_URL="${2:?--article-url requires a value}"; shift 2 ;;
    --symbol) SYMBOL="${2:?--symbol requires a value}"; shift 2 ;;
    --index) MARKET_INDEX="${2:?--index requires a value}"; shift 2 ;;
    --collector-agent) COLLECTOR_AGENT="${2:?--collector-agent requires a value}"; shift 2 ;;
    --collector-model) COLLECTOR_MODEL="${2:?--collector-model requires a value}"; shift 2 ;;
    --sol-agent) SOL_AGENT="${2:?--sol-agent requires a value}"; shift 2 ;;
    --sol-model) SOL_MODEL="${2:?--sol-model requires a value}"; shift 2 ;;
    --summary-model) SUMMARY_MODEL="${2:?--summary-model requires a value}"; shift 2 ;;
    --run-root) RUN_ROOT="${2:?--run-root requires a value}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "error: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z "${MODE}" ]]; then
  echo "error: network and agent execution are disabled by default; choose --live or --stubbed" >&2
  exit 2
fi
if [[ -z "${ARTICLE_URL}" ]]; then
  echo "error: --article-url is required" >&2
  exit 2
fi
if ! [[ "${RUN_DATE}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || \
   ! python3 - "${RUN_DATE}" <<'PY'
from datetime import date
import sys
try:
    date.fromisoformat(sys.argv[1])
except ValueError:
    raise SystemExit(1)
PY
then
  echo "error: --date must be a valid YYYY-MM-DD date" >&2
  exit 2
fi
if ! [[ "${AGENT_TIMEOUT}" =~ ^[1-9][0-9]*$ ]]; then
  echo "error: MINERVA_E2E_AGENT_TIMEOUT must be a positive integer" >&2
  exit 2
fi
if [[ "$(printf '%s' "${SYMBOL}" | tr '[:lower:]' '[:upper:]')" == \
      "$(printf '%s' "${MARKET_INDEX}" | tr '[:lower:]' '[:upper:]')" ]]; then
  echo "error: --symbol and --index must identify different instruments" >&2
  exit 2
fi
if [[ "${MODE}" == "stubbed" ]]; then
  if [[ "${OPENCLAW_COMMAND}" == "openclaw" || "${MINERVA_RUNNER}" == "uv run minerva" ]]; then
    echo "error: --stubbed requires MINERVA_E2E_OPENCLAW and MINERVA_RUNNER test doubles" >&2
    exit 2
  fi
fi

mkdir -p "${RUN_ROOT}"
RUN_DIR="$(mktemp -d "${RUN_ROOT%/}/news-e2e-${RUN_DATE}-XXXXXX")"
DB_PATH="${RUN_DIR}/scratch.db"
BRIEF_PATH="${RUN_DIR}/dry-run-brief.md"
LOG_DIR="${RUN_DIR}/logs"
PROMPT_DIR="${RUN_DIR}/prompts"
mkdir -p "${LOG_DIR}" "${PROMPT_DIR}"

# A newly allocated path beneath RUN_DIR is the only DB this workflow accepts.
if [[ -e "${DB_PATH}" ]]; then
  echo "error[setup]: scratch DB unexpectedly exists: ${DB_PATH}" >&2
  exit 1
fi

IFS=' ' read -r -a MINERVA_RUNNER_ARR <<< "${MINERVA_RUNNER}"
run_minerva() { "${MINERVA_RUNNER_ARR[@]}" "$@"; }
printf -v MINERVA_COMMAND '%q ' "${MINERVA_RUNNER_ARR[@]}"
MINERVA_COMMAND="${MINERVA_COMMAND% }"
printf -v ROOT_Q '%q' "${ROOT_DIR}"
printf -v DB_Q '%q' "${DB_PATH}"
printf -v BRIEF_Q '%q' "${BRIEF_PATH}"
printf -v SUMMARY_MODEL_Q '%q' "${SUMMARY_MODEL}"

render_prompt() {
  local template="$1" destination="$2"
  python3 - "$template" "$destination" "$RUN_DATE" "$ARTICLE_URL" \
    "$SYMBOL" "$MARKET_INDEX" "$ROOT_DIR" "$DB_PATH" "$BRIEF_PATH" \
    "$MINERVA_COMMAND" "$ROOT_Q" "$DB_Q" "$BRIEF_Q" "$SUMMARY_MODEL_Q" <<'PY'
import sys
from pathlib import Path

(template, destination, run_date, article_url, symbol, market_index,
 root, db, brief, minerva, root_q, db_q, brief_q, summary_model_q) = sys.argv[1:]
text = Path(template).read_text(encoding="utf-8")
values = {
    "DATE": run_date,
    "ARTICLE_URL": article_url,
    "SYMBOL": symbol,
    "INDEX": market_index,
    "ROOT": root,
    "DB": db,
    "BRIEF": brief,
    "MINERVA": minerva,
    "ROOT_Q": root_q,
    "DB_Q": db_q,
    "BRIEF_Q": brief_q,
    "SUMMARY_MODEL_Q": summary_model_q,
}
for key, value in values.items():
    text = text.replace("{{" + key + "}}", value)
Path(destination).write_text(text, encoding="utf-8")
PY
}

fail_phase() {
  local phase="$1" status="$2" log_file="$3"
  echo "error[${phase}]: failed with status ${status}" >&2
  echo "error[${phase}]: log: ${log_file}" >&2
  echo "error[${phase}]: preserved run directory: ${RUN_DIR}" >&2
  exit "${status}"
}

invoke_agent() {
  local phase="$1" agent="$2" model="$3" prompt_file="$4" log_file="$5"
  local session_id="news-e2e-${phase}-${RUN_DATE}-$$-${RANDOM}"
  local prompt
  prompt="$(<"${prompt_file}")"
  if "${OPENCLAW_COMMAND}" agent \
      --agent "${agent}" \
      --timeout "${AGENT_TIMEOUT}" \
      --model "${model}" \
      --thinking high \
      --session-id "${session_id}" \
      --message "${prompt}" >"${log_file}" 2>&1; then
    return 0
  else
    local status=$?
    fail_phase "${phase}" "${status}" "${log_file}"
  fi
}

export UV_CACHE_DIR="${UV_CACHE_DIR:-${ROOT_DIR}/.uv-cache}"
export MINERVA_WORKSPACE_ROOT="${RUN_DIR}/workspace"

# Progress belongs on stderr so successful stdout remains one machine-readable
# JSON result.
echo "news-e2e: run_dir=${RUN_DIR}" >&2
echo "news-e2e: mode=${MODE} db=${DB_PATH}" >&2

COLLECTOR_PROMPT="${PROMPT_DIR}/collector.md"
render_prompt "${ROOT_DIR}/scripts/prompts/news_e2e_collector.md" "${COLLECTOR_PROMPT}"
echo "news-e2e: phase=collector" >&2
invoke_agent "collector" "${COLLECTOR_AGENT}" "${COLLECTOR_MODEL}" \
  "${COLLECTOR_PROMPT}" "${LOG_DIR}/collector.log"

# These are the exact live command surfaces. In stubbed mode MINERVA_RUNNER is
# an explicit test double that receives the same argument vectors.
echo "news-e2e: phase=finnhub" >&2
if run_minerva news download-finnhub \
    --date "${RUN_DATE}" --db "${DB_PATH}" --symbol "${SYMBOL}" \
    >"${LOG_DIR}/finnhub.json" 2>"${LOG_DIR}/finnhub.stderr"; then
  :
else
  status=$?
  fail_phase "finnhub" "${status}" "${LOG_DIR}/finnhub.stderr"
fi

echo "news-e2e: phase=market-data" >&2
if run_minerva news download-market-data \
    --date "${RUN_DATE}" --db "${DB_PATH}" --index "${MARKET_INDEX}" \
    --symbol "${SYMBOL}" >"${LOG_DIR}/market-data.json" \
    2>"${LOG_DIR}/market-data.stderr"; then
  :
else
  status=$?
  fail_phase "market-data" "${status}" "${LOG_DIR}/market-data.stderr"
fi

SOL_PROMPT="${PROMPT_DIR}/sol.md"
render_prompt "${ROOT_DIR}/scripts/prompts/news_e2e_sol.md" "${SOL_PROMPT}"
echo "news-e2e: phase=sol" >&2
invoke_agent "sol" "${SOL_AGENT}" "${SOL_MODEL}" \
  "${SOL_PROMPT}" "${LOG_DIR}/sol.log"

echo "news-e2e: phase=verify" >&2
if python3 - "${DB_PATH}" "${BRIEF_PATH}" "${ARTICLE_URL}" "${SYMBOL}" \
    "${MARKET_INDEX}" "${RUN_DIR}" >"${RUN_DIR}/result.json" \
    2>"${LOG_DIR}/verify.stderr" <<'PY'
import json
import sqlite3
import sys
from pathlib import Path

(db_raw, brief_raw, article_url, symbol, market_index, run_dir) = sys.argv[1:]
db = Path(db_raw)
brief = Path(brief_raw)
errors: list[str] = []
counts = {"collector_rows": 0, "finnhub_rows": 0, "market_rows": 0, "null_summaries": 0}

if not db.is_file():
    errors.append("scratch DB does not exist")
else:
    try:
        uri = f"{db.resolve().as_uri()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as conn:
            conn.execute("PRAGMA query_only = ON")
            tables = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            if "news" not in tables:
                errors.append("news table does not exist")
            else:
                counts["collector_rows"] = conn.execute(
                    "SELECT COUNT(*) FROM news WHERE source=? AND url=?",
                    ("e2e-collector", article_url),
                ).fetchone()[0]
                counts["finnhub_rows"] = conn.execute(
                    "SELECT COUNT(*) FROM news WHERE section IN (?, ?)",
                    ("finnhub-general", "finnhub-company"),
                ).fetchone()[0]
                counts["null_summaries"] = conn.execute(
                    "SELECT COUNT(*) FROM news "
                    "WHERE summary IS NULL OR trim(summary) = ''"
                ).fetchone()[0]
            if "prices" not in tables:
                errors.append("prices table does not exist")
            else:
                expected_prices = (
                    (symbol.upper(), "security"),
                    (market_index.upper(), "index"),
                )
                missing_prices = []
                for ticker, instrument_type in expected_prices:
                    found = conn.execute(
                        "SELECT 1 FROM prices WHERE ticker=? AND instrument_type=? "
                        "AND previous_close IS NOT NULL AND change_pct IS NOT NULL "
                        "LIMIT 1",
                        (ticker, instrument_type),
                    ).fetchone()
                    if found is None:
                        missing_prices.append(f"{ticker} ({instrument_type})")
                    else:
                        counts["market_rows"] += 1
                if missing_prices:
                    errors.append(
                        "market rows missing type/previous_close/change_pct: "
                        + ", ".join(missing_prices)
                    )
    except sqlite3.Error as exc:
        errors.append(f"SQLite verification failed: {exc}")

if counts["collector_rows"] < 1:
    errors.append("collector row was not found")
if counts["finnhub_rows"] < 1:
    errors.append("no Finnhub rows were found")
if counts["null_summaries"]:
    errors.append(f"{counts['null_summaries']} news row(s) still lack summaries")
try:
    brief_nonempty = bool(brief.read_text(encoding="utf-8").strip())
except OSError:
    brief_nonempty = False
if not brief_nonempty:
    errors.append("dry-run brief is missing or empty")

if errors:
    for error in errors:
        print(f"verification: {error}", file=sys.stderr)
    raise SystemExit(1)

result = {
    "brief_nonempty": True,
    **counts,
    "ok": True,
    "run_dir": run_dir,
}
print(json.dumps(result, separators=(",", ":"), sort_keys=True))
PY
then
  cat "${RUN_DIR}/result.json"
else
  status=$?
  fail_phase "verify" "${status}" "${LOG_DIR}/verify.stderr"
fi
