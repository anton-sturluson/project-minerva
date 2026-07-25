# Browser CLI

`browser` controls Chrome through a local command server and a Manifest V3 extension bridge. It does not launch a headless browser: commands operate on a dedicated managed Chrome window, while `close-idle` is the one explicitly global cleanup command.

## Architecture

```text
browser (CLI)
  -> local command server (Unix socket, with localhost fallback)
    -> WebSocket bridge (ws://127.0.0.1:19224)
      -> Chrome MV3 extension service worker
        -> chrome.tabs / chrome.scripting / Chrome DevTools Protocol
```

The first page command creates a dedicated automation window and managed tab. Later commands use that tab unless `--new`, `--window`, or a command-specific `--tab <alias>` is supplied. Managed tabs have sequential aliases (`t0`, `t1`, ...).

## Setup

Requirements: Node.js 20 or newer and Chrome/Chromium 121 or newer. Chrome 121 includes the MV3 WebSocket service-worker lifetime behavior, 30-second alarms, and `tabs.lastAccessed` data required by the bridge and `close-idle`.

```bash
cd src/browser
npm install
npm run build
npm link                    # optional: installs the `browser` command
```

Load the extension:

1. Open `chrome://extensions`.
2. Enable **Developer mode**.
3. Click **Load unpacked**.
4. Select `src/browser/extension`.
5. Keep Chrome running, then check the connection with `browser status`.

The CLI starts its local server on the first command. Concurrent cold starts elect one command-server winner without unlinking a live socket; only that winner binds the extension bridge. Run `browser stop` to stop it. The local Unix socket is owner-only where supported; the TCP and WebSocket fallbacks bind to `127.0.0.1`. The loopback HTTP command endpoint rejects every request carrying an `Origin` header and accepts only `application/json`, preventing browser pages and no-CORS requests from dispatching commands without relying on CORS response policy.

The WebSocket server accepts only `chrome-extension://` origins and promotes a connection only after the expected extension hello handshake; unauthenticated candidates time out. This prevents ordinary web pages from replacing the extension. It is not a shared-secret pairing protocol: another process running as the same local user can still connect to loopback while impersonating an extension origin, so the same-user local-process trust boundary remains.

## Usage

```bash
# Default managed tab
browser open "https://news.ycombinator.com"
browser snapshot
browser extract ".titleline" --json --limit 5
browser click "More"
browser type "Search" "browser CLI"
browser screenshot ./artifacts/page.png
browser status

# Multiple managed tabs
browser open "https://site-a.example"          # creates t0
browser open "https://site-b.example" --new    # creates and activates t1
browser tabs
browser snapshot --tab t0
browser focus t0
browser close t1

browser stop
```

Run `browser help` for the command list or `browser <command> --help` for exact arguments and options. Options are command-specific: unsupported flags, duplicate flags, ambiguous combinations, and surplus positional arguments fail instead of being ignored.

## `close-idle` safety

`browser close-idle` is intentionally **global**. Unlike action commands, it considers both managed and unmanaged tabs across all Chrome windows. Only tabs in normal windows can be closed.

Always preview first:

```bash
browser close-idle --hours 6 --dry-run
browser close-idle --hours 6
```

Safety rules:

- `--hours` is required and must be a positive safe integer. Values such as `0`, `1.5`, `6hours`, and unsafe integers are rejected.
- `--tab` and every unrelated option are rejected because cleanup is global.
- Pinned, audible, active, non-normal-window, recently accessed, and timestamp-less tabs are always skipped. “Active” includes the active tab in every background window, not only the focused window.
- Every initially eligible candidate is fetched, has its window checked, and is then fetched a final time immediately before its individual removal. A tab that became active, pinned, audible, recent, or moved while the window lookup was pending is skipped.
- Tabs are removed one at a time. A vanished tab or one failed operation does not abort later candidates.
- Output separately reports eligible, closed, skipped, and failed counts, with skip reasons and per-tab failures.
- Managed-tab registry cleanup is batched and idempotent; `chrome.tabs.onRemoved` and command cleanup cannot cause duplicate state writes.

`--dry-run` performs the same candidate revalidation but never calls `chrome.tabs.remove`.

## Oracle commands

`browser describe` and `browser ask` capture a screenshot and accessibility tree, then call OpenRouter. Set `OPENROUTER_API_KEY` in the environment or a nearby `.env` file. Other commands do not require an external API.

## Development and verification

```bash
npm run check       # TypeScript typecheck + syntax-check extension modules
npm test            # parser, close-idle, state/concurrency, formatting, and smoke tests
npm run build       # compile src/ to dist/
npm run smoke       # invoke every command through offline fakes
```

The smoke suite parses and dispatches every command without starting the WebSocket server, connecting to Chrome, closing tabs, or calling OpenRouter. Live Chrome behavior still requires manually loading the unpacked extension; automated tests intentionally do not perform destructive live-browser operations.

## Notes

- `screenshot` targets the selected tab only through Chrome DevTools Protocol. If full-page capture fails, it attempts a target-specific CDP viewport capture; if both fail, the command reports both errors rather than risking a screenshot of another tab.
- `wait --stable` fingerprints the selected subtree's DOM, text, form state, key computed styles, scroll dimensions/position, and bounding rectangle; it returns after that fingerprint is unchanged for 500 ms.
- Accessibility snapshot baselines, element refs (`e1`, `e2`, ...), and dialog state are scoped per managed tab.
- Managed aliases persist through extension service-worker restarts using `chrome.storage.session`.
- If the bridge disconnects, reload the extension in `chrome://extensions` and run `browser status`.
