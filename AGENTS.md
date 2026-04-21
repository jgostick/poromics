# Agent Operating Guide

This file is the fast-start index for coding sessions in this repository.

## Quick Session Checklist

1. Read this file first.
2. Read `docs/guides/README.md`.
3. Open the architecture docs in `docs/architecture/` when touching system behavior.
4. Use Makefile commands by default.
5. Keep changes small, consistent, and aligned with existing patterns.

## Where to Find Guidance

### Focused agent guidance

- `docs/guides/backend-django.md`
- `docs/guides/frontend-ui.md`
- `docs/guides/operations-jobs.md`

### Architecture and implementation documentation

- `docs/architecture/system-overview.md`
- `docs/architecture/team-tenancy.md`
- `docs/architecture/compute-routing.md`
- `docs/architecture/operational-learnings.md`

## Non-Negotiable Conventions

- Do not create agent-specific directories (e.g. `.claude/`, `.cursor/`, `.codex/`). All agent guidance lives in `docs/guides/` and `AGENTS.md`. Memory and note files belong in `docs/` or the project root.
- Prefer simple solutions and avoid duplicate logic.
- Do not introduce new patterns/tech unless existing approach is exhausted.
- Do not overwrite `.env` without explicit confirmation.
- Team-owned models should use `BaseTeamModel`; non-team models should use `BaseModel`.
- Team-scoped logic should respect `/a/<team_slug>/...` routing and team decorators.
- Validate user input server-side and handle errors explicitly.
- Use generated OpenAPI client for frontend API interactions where applicable.

## Common Commands

```bash
make
make init
make dev
make test
make ruff
make manage ARGS='command'
```

## Remote Compute Notes

- Julia and Taichi queue routing is settings-driven.
- Queue names stay stable; endpoints select local vs remote behavior.
- See `docs/architecture/compute-routing.md` for details.

## Documentation Maintenance Rule

When behavior changes:

1. Update user-facing setup in `README.md` if usage changed.
2. Update architecture docs in `docs/architecture/` if implementation changed.
3. Update `docs/guides/` if coding-agent workflow or conventions changed.
