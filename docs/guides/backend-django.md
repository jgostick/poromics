# Backend and Django Guide

## Architecture Defaults

- Framework: Django with function-based views by default.
- Keep implementation simple and aligned with existing patterns.
- Reuse existing services/utilities before introducing new abstractions.

## Model Conventions

- Team-owned models should inherit `apps.teams.models.BaseTeamModel`.
- Non-team models should inherit `apps.utils.models.BaseModel`.
- Use `for_team` manager for context-scoped queries where applicable.
- Import user model as `apps.users.models.CustomUser`.

## URL and Team Conventions

- Many apps define both `urlpatterns` and `team_urlpatterns`.
- Team-scoped URLs are mounted under `/a/<team_slug>/...`.
- Team views should include `team_slug` first in signature.
- Prefer `@login_and_team_required` / `@team_admin_required` in team contexts.

## Views and Validation

- Validate user input server-side in all cases.
- Handle errors explicitly.
- Avoid silent failure behavior.

## Data Access and Performance

- Prefer Django ORM over raw SQL when practical.
- Use `select_related`/`prefetch_related` intentionally for query efficiency.
- Avoid unnecessary eager evaluation of querysets.

## Style and Tooling

- PEP 8 with 120-character line limit.
- Double quotes for Python strings.
- Ruff handles format/lint/isort.

Common commands:

- `make ruff`
- `make test`
- `make manage ARGS='...'`
