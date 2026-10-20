#!/usr/bin/env bash
# Fixed scheduler entry point. Use inherited source configuration only.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.."; pwd -P)"
cd "${ROOT_DIR}"

fail() {
  echo "error[preflight]: $*" >&2
  exit 1
}

check_main() {
  local branch status
  [[ -d "${ROOT_DIR}/.git" ]] || fail "run from the primary checkout, not a linked worktree"
  [[ "$(git rev-parse --show-toplevel)" == "${ROOT_DIR}" ]] || fail "unexpected repository root"
  branch="$(git symbolic-ref --quiet --short HEAD)" || fail "checkout must be on named branch main"
  [[ "${branch}" == main ]] || fail "checkout must be on named branch main"
  status="$(git status --porcelain --untracked-files=all)" || fail "cannot inspect checkout status"
  [[ -z "${status}" ]] || fail "checkout must be clean; preserve unexpected changes manually"
}

check_main
# Never reset, stash, rebase, or merge divergent history in the shared runtime.
git fetch --quiet origin refs/heads/main:refs/remotes/origin/main >&2
git merge --ff-only --quiet origin/main >&2
check_main
HEAD_REV="$(git rev-parse --verify HEAD)"
ORIGIN_REV="$(git rev-parse --verify refs/remotes/origin/main)"
[[ "${HEAD_REV}" == "${ORIGIN_REV}" ]] || fail "HEAD differs from origin/main"

export UV_PROJECT_ENVIRONMENT="${ROOT_DIR}/.venv"
export UV_CACHE_DIR="${UV_CACHE_DIR:-${ROOT_DIR}/.tmp/uv-cache}"
# Dependency setup can write to stderr even on success. A command automation
# combines both streams, so emit only the silent token after successful handoff.
if runner_output="$(uv run --project "${ROOT_DIR}" python \
  "${ROOT_DIR}/scripts/morning_brief_presync.py" "$@" 2>&1)"; then
  printf '%s\n' 'NO_REPLY'
else
  exit_status=$?
  printf 'error[scheduled-launch]: runner failed with status %s\n' "${exit_status}" >&2
  printf '%s\n' "${runner_output}" | tail -c 8192 >&2
  exit "${exit_status}"
fi
