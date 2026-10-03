# IP-002 verification

Verified 2026-10-01 using PostgreSQL 17 and synthetic data.

- Twelve backend tests passed, including fresh migrations applied twice, account persistence after reconnect, repeated create requests, invalid fields, cross-workspace isolation, and refusal of hosted local identity.
- Twelve desktop/mobile Chromium checks passed, covering account creation/reload, API connectivity, and account-load failure/recovery. The browser suite uses a separate database from the manual demo.
- Live in-app browser: created “Demo portfolio” in USD; stopped PostgreSQL and reloaded to see the records-unavailable message; restarted PostgreSQL and confirmed the same account persisted. Inspected the 390px layout with no horizontal page overflow.
- Python lint/format, frontend formatting/typecheck/build passed.

Docker is not installed on the development machine, so manual verification used a loopback-bound native PostgreSQL 17 installation. Compose is supplied for repeatable setup; CI uses the PostgreSQL 17 service image. Account currency is immutable through the API. This increment has no cash or trades yet.
