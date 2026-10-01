# Contributing

Welcome! Nori is an early local-first assistant. Discuss larger changes
in an issue first; small fixes and documentation improvements can go directly to a PR.

1. Install Python 3.12+, uv and Node 22.19+.
2. Run `uv sync --locked` and `npm ci --prefix services/agent-runtime --ignore-scripts`.
3. Read `AGENTS.md` and the module boundaries in `docs/repository-layout.md`.
4. Keep changes focused. Add meaningful tests for behavior changes. Use synthetic
   fixtures; never include your inbox, API keys, OAuth tokens, or local databases.
5. Run the checks below and explain the change and validation in your PR.

```sh
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
npm run check --prefix services/agent-runtime
npm test --prefix services/agent-runtime
npm test --prefix apps/web
uv run python scripts/check-secrets.py
```

Docker integration tests are opt-in: build the image as documented in
`docs/desktop.md`, then run `RUN_CONTAINER_TESTS=1 uv run pytest -q`.
Normal checks do not require model keys, Google authorization or Docker.

Contributions are submitted under the project's Apache-2.0 license.
