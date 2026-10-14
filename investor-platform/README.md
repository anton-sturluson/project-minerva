# Investor Platform

A local-first portfolio tracker inside Minerva, built with React/TypeScript, FastAPI and PostgreSQL. Track cash and trades, compare returns with SPY/QQQ, and review payoff ratio and decision hit rate. Incomplete imports are labeled provisional. Research includes a sourced manager directory and imported quarterly SEC holdings comparisons.

## Run locally

Requires Docker Compose, uv, Python 3.12, Node 22 and pnpm 11. Exact versions are pinned in the backend and frontend projects. No API key is required.

From the repository root, start PostgreSQL:

```sh
docker compose -f investor-platform/compose.yml up -d --wait
```

Start the API:

```sh
cd investor-platform/backend
uv sync --frozen
uv run --frozen alembic upgrade head
uv run --frozen investor-api
```

In a second terminal, from the repository root:

```sh
cd investor-platform/web
pnpm install --frozen-lockfile
pnpm dev
```

Open **http://127.0.0.1:5173/**. Ctrl+C stops each app process. The default database credentials are local development examples; keep PostgreSQL bound to loopback.

See the [documentation index](docs/README.md) for configuration, private Tailscale access, testing, portfolio workflows and calculation methods.
