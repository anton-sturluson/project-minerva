#!/usr/bin/env bash

# Load the shell environment needed by the collection pipeline and OpenClaw
# before strict mode. The collection script does this too, but exports made in
# a child do not propagate back to this wrapper.
source ~/.zshrc >/dev/null 2>&1 || true

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.."; pwd)"
RUN_DATE="${1:-$(date +%F)}"
WORKSPACE_ROOT="${MINERVA_WORKSPACE_ROOT:-${ROOT_DIR}/hard-disk}"
REPORT_DIR="${WORKSPACE_ROOT}/reports/03-daily-news/${RUN_DATE}"
INVEST_DB="${INVEST_DB:-${WORKSPACE_ROOT}/data/04-database/invest.db}"
PREPARED_PATH="${REPORT_DIR}/data/structured/prepared-evidence.json"
RENDERED_DIR="${REPORT_DIR}/data/rendered"
OUTPUT_PATH="${REPORT_DIR}/notes/slack-brief.md"
PIPELINE_LOG="${MINERVA_MORNING_BRIEF_LOG:-${TMPDIR:-/tmp}/minerva-morning-brief-pipeline-${RUN_DATE}.log}"
SYNTHESIS_LOG="${MINERVA_MORNING_BRIEF_SYNTHESIS_LOG:-${TMPDIR:-/tmp}/minerva-morning-brief-synthesis-${RUN_DATE}.log}"
PIPELINE_SCRIPT="${MINERVA_MORNING_BRIEF_PIPELINE_SCRIPT:-${ROOT_DIR}/scripts/run_morning_brief.sh}"
SYNTHESIS_RUNNER="${MINERVA_SYNTHESIS_RUNNER:-uv run python -m harness.morning_brief_synthesis}"
SYNTHESIS_MODEL="${MINERVA_BRIEF_SYNTHESIS_MODEL:-gpt-5.6-sol}"

mkdir -p "$(dirname "${PIPELINE_LOG}")" "$(dirname "${SYNTHESIS_LOG}")"
export MINERVA_WORKSPACE_ROOT="${WORKSPACE_ROOT}"
export INVEST_DB

# Collection, extraction, SQLite ingestion, and evidence preparation must all
# finish successfully before the first OpenClaw Sol turn. Retry the complete wrapper
# once on a non-zero exit or a missing/empty rendered evidence directory.
# Noisy output stays out of cron stdout, which is reserved for the final brief.
pipeline_status=1
for attempt in 1 2; do
  printf '\n=== pipeline attempt %s ===\n' "${attempt}" >>"${PIPELINE_LOG}"
  set +e
  bash "${PIPELINE_SCRIPT}" "${RUN_DATE}" >>"${PIPELINE_LOG}" 2>&1
  pipeline_status=$?
  set -e
  if [[ "${pipeline_status}" -eq 0 ]] && [[ -d "${RENDERED_DIR}" ]] && find "${RENDERED_DIR}" -maxdepth 1 -type f -print -quit | grep -q .; then
    break
  fi
  pipeline_status=1
done
if [[ "${pipeline_status}" -ne 0 ]]; then
  echo "morning-brief collection pipeline failed twice or produced no rendered evidence; Sol was not invoked" >&2
  echo "pipeline log: ${PIPELINE_LOG}" >&2
  tail -n 40 "${PIPELINE_LOG}" >&2 || true
  exit 1
fi

IFS=' ' read -r -a SYNTHESIS_RUNNER_ARR <<< "${SYNTHESIS_RUNNER}"
set +e
"${SYNTHESIS_RUNNER_ARR[@]}" \
  --date "${RUN_DATE}" \
  --workspace-root "${WORKSPACE_ROOT}" \
  --db "${INVEST_DB}" \
  --prepared-evidence "${PREPARED_PATH}" \
  --output "${OUTPUT_PATH}" \
  --model "${SYNTHESIS_MODEL}" 2>"${SYNTHESIS_LOG}"
synthesis_status=$?
set -e
if [[ "${synthesis_status}" -ne 0 ]]; then
  echo "morning-brief synthesis failed with status ${synthesis_status}" >&2
  echo "synthesis log: ${SYNTHESIS_LOG}" >&2
  tail -n 40 "${SYNTHESIS_LOG}" >&2 || true
  exit "${synthesis_status}"
fi

rm -f "${PIPELINE_LOG}" "${SYNTHESIS_LOG}"
