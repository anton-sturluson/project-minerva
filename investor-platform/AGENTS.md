# Investor Platform

- Keep each ticket in one PR. Do not bundle the next ticket into the current feature.
- Portfolio state belongs in PostgreSQL. Existing data may be migrated once; do not introduce sheet sync, sheet-shaped domain models, or a spreadsheet dependency into the app.
- Use the independent backend uv project and frontend pnpm project. Preserve their lockfiles.
- Add only the folders and dependencies needed by the current ticket.
- Include correctness checks with the feature that introduces the behavior.
- Use a separate synthetic testing portfolio for live/browser verification; never mutate real portfolio records for tests.
- Live-test each increment in the browser: normal behavior, relevant failure/recovery behavior, and mobile layout. Report what was actually exercised. Keep user updates brief.
- Run backend lint/tests, frontend formatting/build, and relevant browser tests before opening a PR. Use synthetic data for committed fixtures.
- Follow the repository-root worktree convention: `worktrees/`.
