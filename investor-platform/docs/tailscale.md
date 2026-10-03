# Private access with Tailscale

This runs the existing single-owner workspace on your Mac and makes it reachable from your own Tailscale devices. It is not public hosting or multi-user login. Use synthetic records until verified backup/restore is implemented.

## First setup on the host

Install and sign into Tailscale on the host and client devices using the same user. Keep the host awake, PostgreSQL running, and the app terminal open. Use an untagged, user-owned host and client; tagged devices do not supply user identity headers. Tailnet access rules must permit the client to reach the host on TCP 8444. [Serve documentation](https://tailscale.com/docs/features/tailscale-serve)

Follow the README prerequisites for uv, pnpm, and PostgreSQL. From the repository root, explicitly choose the database to serve, then run:

```sh
export DATABASE_URL='postgresql+psycopg://minerva:minerva-local-only@127.0.0.1:55432/minerva_test'
./investor-platform/scripts/run-tailscale.sh
```

The example selects the separate synthetic demo database used during development; it must already exist. The runner applies migrations but does not create the database or seed a portfolio. Change the database name deliberately for a different workspace. The development password is only for loopback PostgreSQL.

The runner discovers the host's Tailscale DNS name and owning user, builds the frontend, migrates the selected database, and starts the protected app on **127.0.0.1:8011**. It prints the allowed user and private URL. No secrets or personal Tailscale addresses are checked into configuration. `TAILSCALE_BIN` optionally overrides CLI discovery.

In a second terminal, configure the dedicated listener once. On macOS with the standalone Tailscale app:

```sh
TS=/Applications/Tailscale.app/Contents/MacOS/Tailscale
"$TS" serve status
# Confirm 8444 is unused before adding it; preserve unrelated listeners.
"$TS" serve --bg --https=8444 http://127.0.0.1:8011
"$TS" serve status
```

If the CLI is on PATH, use `TS=$(command -v tailscale)`. Serve may ask you to enable HTTPS in your tailnet. Only proceed with that setup if needed. Port 8444 is dedicated to this app and is outside Funnel's supported public ports. Do not use `serve reset`, which would remove other services. [Serve CLI](https://tailscale.com/docs/reference/tailscale-cli/serve), [Funnel restrictions](https://tailscale.com/docs/features/tailscale-funnel)

## Connect and restart

1. Connect Tailscale on your phone or other computer, signed in as the user printed by the runner.
2. Open the printed **https://machine.tailnet.ts.net:8444/** URL in a browser. Keep the port in the URL. There is no separate app password.
3. After a Mac or app restart, start PostgreSQL and rerun the script with the same `DATABASE_URL`. The background Serve configuration persists; check `serve status` if necessary. The app itself does not auto-start.

Ctrl+C stops the app without deleting records. To remove only this app's network listener:

```sh
"$TS" serve --https=8444 off
```

## Access boundary and troubleshooting

Tailscale Serve strips caller-supplied identity headers and inserts the authenticated user's identity. The app accepts exactly one configured `Tailscale-User-Login`, the exact HTTPS authority and origin, and a loopback socket peer. Writes require the matching Origin header. HTML, assets, API routes, and API documentation all share this gate. Uvicorn proxy-header rewriting is disabled. Do not bind the backend to a LAN address, proxy it through another service, or expose local development port 8010/5173. Local processes on the host are trusted. [Identity headers](https://tailscale.com/docs/features/tailscale-serve)

- **403:** Check that both devices belong to the same printed user and are not tagged. Missing/foreign identity, other hosts/origins, and direct access to port 8011 are rejected. Funnel does not provide user identity, so it cannot pass the gate.
- **502 / service unavailable:** Restart the app. An already-open form retains its draft; retry it unchanged after recovery. Check PostgreSQL when the API reports database unavailability.
- **Cannot connect:** Check Tailscale connectivity, host sleep, Serve status, HTTPS setup, and tailnet access rules. Do not solve connectivity by enabling public Funnel.
- **Missing frontend build:** Use the runner; it builds the frontend before starting the app.

The manual equivalent uses `INVESTOR_MODE=tailscale`, `TAILSCALE_ORIGIN=https://machine.tailnet.ts.net:8444`, and `TAILSCALE_USER_LOGIN` before `uv run --frozen investor-api` in `backend/`. Unknown modes and incomplete configuration fail at startup. All accepted Tailscale requests map to the existing single local workspace; additional user accounts remain future work.

## Verification

Tested with a separate synthetic portfolio: private HTTPS load, a cash deposit, backend shutdown with a retained withdrawal draft, successful retry after restart, persisted records after reload, SPY/QQQ comparison, and mobile layout. Access-control tests cover missing/foreign/duplicate identity, non-loopback peers, host/origin restrictions, required write origins, invalid configuration, and missing builds. The existing local desktop/mobile suite also remains required.

## References

### Tailscale

- [Serve](https://tailscale.com/docs/features/tailscale-serve) — private access, identity headers, loopback trust boundary, and tagged-device limitations.
- [Serve CLI](https://tailscale.com/docs/reference/tailscale-cli/serve) — listener configuration, background operation, and per-port removal.
- [Funnel](https://tailscale.com/docs/features/tailscale-funnel) — public exposure and supported public ports.
