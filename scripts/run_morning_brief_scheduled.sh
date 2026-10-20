#!/usr/bin/env bash
# Existing portfolio sync must succeed before the existing agent job starts.
set -euo pipefail

[[ "$#" == 2 && "$1" == --handoff-job ]] || {
  echo "usage: $0 --handoff-job JOB_ID" >&2
  exit 1
}
: "${MINERVA_PORTFOLIO_HOLDINGS_SOURCE:?holdings source must be configured}"
: "${MINERVA_PORTFOLIO_TRANSACTIONS_SOURCE:?transactions source must be configured}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.."; pwd -P)"
cd "${ROOT_DIR}"

fail() { echo "error[preflight]: $*" >&2; exit 1; }
run_quietly() {
  local output code
  if output="$("$@" 2>&1)"; then
    return 0
  else
    code=$?
    printf 'error: %s failed with status %s\n' "$1" "${code}" >&2
    printf '%s\n' "${output}" | tail -c 8192 >&2
    exit "${code}"
  fi
}

# Preserve the existing clean-main runtime policy; never repair others' work.
check_main() {
  local branch status
  [[ -d .git ]] || fail "run from the primary checkout, not a linked worktree"
  [[ "$(git rev-parse --show-toplevel)" == "${ROOT_DIR}" ]] || fail "unexpected repository root"
  branch="$(git symbolic-ref --quiet --short HEAD)" || fail "checkout must be on named main"
  [[ "${branch}" == main ]] || fail "checkout must be on main"
  status="$(git status --porcelain --untracked-files=all)" || fail "cannot inspect checkout"
  [[ -z "${status}" ]] || fail "checkout must be clean"
}
check_main
run_quietly git fetch --quiet origin refs/heads/main:refs/remotes/origin/main
run_quietly git merge --ff-only --quiet origin/main
check_main
HEAD_REV="$(git rev-parse --verify HEAD)"
ORIGIN_REV="$(git rev-parse --verify refs/remotes/origin/main)"
[[ "${HEAD_REV}" == "${ORIGIN_REV}" ]] || fail "HEAD differs from origin/main"
export UV_PROJECT_ENVIRONMENT="${ROOT_DIR}/.venv"
export UV_CACHE_DIR="${UV_CACHE_DIR:-${ROOT_DIR}/.tmp/uv-cache}"

RUN_DATE="$(TZ=America/New_York date +%F)"
sync_command=(uv run --project "${ROOT_DIR}" minerva portfolio sync --date "${RUN_DATE}"
  --holdings-source "${MINERVA_PORTFOLIO_HOLDINGS_SOURCE}"
  --transactions-source "${MINERVA_PORTFOLIO_TRANSACTIONS_SOURCE}")
[[ -z "${MINERVA_PORTFOLIO_WATCHLIST_SOURCE:-}" ]] || sync_command+=(--watchlist-source "${MINERVA_PORTFOLIO_WATCHLIST_SOURCE}")

run_quietly "${sync_command[@]}"
run_quietly openclaw automations run "$2" --json
# The agent delivers the brief; the scheduler must not post a second message.
printf '%s\n' 'NO_REPLY'
