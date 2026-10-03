#!/usr/bin/env bash
# Run the built app behind an existing private Tailscale Serve listener on 8444.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${DATABASE_URL:?Set DATABASE_URL to the portfolio database you intend to serve}"
TAILSCALE_BIN="${TAILSCALE_BIN:-$(command -v tailscale || true)}"
if [[ -z "$TAILSCALE_BIN" && -x /Applications/Tailscale.app/Contents/MacOS/Tailscale ]]; then
  TAILSCALE_BIN=/Applications/Tailscale.app/Contents/MacOS/Tailscale
fi
if [[ ! -x "$TAILSCALE_BIN" ]]; then
  echo 'Install and sign into Tailscale first.' >&2
  exit 1
fi
# Read only the current machine and its user; never change other Serve listeners.
identity=$("$TAILSCALE_BIN" status --json | uv run --project backend --frozen python -c '
import json, sys
s = json.load(sys.stdin)
assert s["BackendState"] == "Running", "Tailscale must be connected"
me = s["Self"]
login = s["User"][str(me["UserID"])]["LoginName"]
assert login and not me.get("Tags"), "Use a user-owned Tailscale device"
print("https://" + me["DNSName"].rstrip(".") + ":8444")
print(login)
')
export INVESTOR_MODE=tailscale
export TAILSCALE_ORIGIN="${identity%%$'\n'*}"
export TAILSCALE_USER_LOGIN="${identity#*$'\n'}"
(cd web && pnpm install --frozen-lockfile && pnpm build)
printf 'Private portfolio: %s\nAllowed user: %s\n' "$TAILSCALE_ORIGIN" "$TAILSCALE_USER_LOGIN"
cd backend
uv run --frozen alembic upgrade head
exec uv run --frozen investor-api
