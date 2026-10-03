#!/bin/sh
# Scheduled execution uses the installed CLI in the reviewed checkout.
set -eu
project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_root"
# Optional deployment-owned configuration; this file must stay out of Git.
if [ -f .env.local ]; then
    set -a
    . ./.env.local
    set +a
fi
: "${MINERVA_DATABASE_URL:?Configure the shared Postgres connection}"
: "${MINERVA_IDEAS_ROOT:?Configure the canonical report directory}"
: "${BRAVE_API_KEY:?Configure Brave Search}"
: "${GEMINI_API_KEY:?Configure Gemini}"
job_id="${1:?Pass the existing OpenClaw job ID}"
"$project_root/.venv/bin/minerva" ideas init >/dev/null
exec "$project_root/.venv/bin/minerva" ideas weekly "$job_id" --model "${MINERVA_IDEAS_MODEL:-gemini-2.5-flash-lite}"
