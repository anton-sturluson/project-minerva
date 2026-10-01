# IP-001 verification

Verified locally on 2026-10-01. Scope is the app shell and service connectivity; no portfolio storage or financial calculations are implemented.

## Live browser checks

- Opened the running app in the Codex in-app browser and verified “Connected” against the real FastAPI service.
- Stopped the API process, clicked “Check connection,” and verified the disconnected message.
- Restarted the API, retried, and verified recovery to “Connected.”
- Inspected desktop and 390-pixel mobile rendering. Mobile content width equaled viewport width; cards stacked without horizontal overflow.

## Automated checks

- Six API tests: identifiable health response, no caching, trusted frontend origin, rejected foreign/null/unconfigured origins, and rejected foreign host.
- Eight Chromium checks across desktop/mobile: real API connection and viewport fit; disconnection/recovery; wrong-service/error responses; and request timeout.
- Python formatting/lint, frontend formatting/type checking, and production frontend build.

The first browser-suite attempt overlapped the manual API shutdown and correctly failed its real-API assertions. The full suite passed after restoring the API. Run fault injection separately from the automated suite.

GitHub CI runs the same checks in a fresh Linux environment. Its status is recorded on the PR; local results alone do not establish remote CI success.
