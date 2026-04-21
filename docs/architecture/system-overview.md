# System Overview

## Stack Summary

- Backend: Django on Python 3.12
- Auth: `django-allauth`
- API: Django REST Framework + drf-spectacular schema docs
- Frontend: Django templates + HTMX + Alpine.js
- Styling: Tailwind CSS v4 + DaisyUI
- Frontend bundling: Vite + `django-vite`
- Database: PostgreSQL
- Caching and broker: Redis
- Background jobs: Celery + `django-celery-beat`

## Major Application Areas

- `apps/users`: custom user model and account flows.
- `apps/teams`: team tenancy, memberships, invitations, team context.
- `apps/pore_analysis`: upload, analysis workflows, jobs, results, pricing.
- `apps/api`: API auth and API-facing behavior.
- `apps/web`, `apps/dashboard`, `apps/support`: primary web-facing pages and support utilities.

## Request and Routing Model

- Team-scoped routes are mounted under `/a/<team_slug>/...` in `poromics/urls.py`.
- Non-team routes remain under global paths.
- Team routes generally use team-aware decorators and expect `team_slug` in view signatures.

In practical terms, views operate in one of two contexts:

1. Global context (no team selected in URL)
2. Team context (team selected in URL and request middleware)

## Team Context Flow

`apps/teams/middleware.py` injects lazy team context onto the request:

- `request.team`
- `request.default_team`
- `request.team_membership`

Team-scoped models should use `BaseTeamModel` from `apps/teams/models.py` and query through `for_team` when filtering by current context.

## Analysis Job Lifecycle

Core data model and lifecycle are centered on `apps/pore_analysis`:

1. User submits analysis request against an uploaded image.
2. Backend validates parameters and estimates/charges cost.
3. Celery task is queued (queue selection depends on backend and analysis type).
4. Task runs analysis pipeline and stores result payload in `AnalysisResult.metrics`.
5. Job transitions through status states and refund logic applies on failure.

The project persists routing and execution metadata in job parameters to aid tracing/debugging.

## Background Processing

`poromics/celery.py` configures Celery app loading. Jobs are primarily defined in `apps/pore_analysis/tasks.py`.

Key tasks include:

- permeability jobs
- diffusivity jobs
- pore-size jobs
- pore-network extraction jobs

Some tasks are retried with backoff; some intentionally do not retry (for example, current diffusivity behavior).

## Frontend Integration Pattern

The project favors server-rendered templates with progressive enhancement:

- HTMX for server-backed interactions
- Alpine.js for browser-only state and interactions
- Vite-built assets loaded via template tags from `django-vite`

This keeps Django templates as the source of truth while allowing dynamic UX where needed.
