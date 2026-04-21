# Operational Learnings and Gotchas

This document captures implementation details that repeatedly matter in day-to-day development.

## Remote Compute Routing

- Queue-scoped endpoint routing is settings-driven for both Julia and Taichi.
- Queue naming should remain stable; endpoint choice determines local vs remote behavior.
- Persisting queue and endpoint metadata in job parameters improves observability and debugging.

## Gallery Metrics Refresh

From recent image gallery work:

- Bulk metrics refresh endpoint lives in `apps/pore_analysis/views/image_management.py`.
- Team route name is `pore_analysis_team:refresh_image_metrics` at `/images/refresh-metrics/`.
- `compute_metrics` may return empty dict on failure; empty result should be treated as failed refresh.
- `get_image_metrics` outputs must be JSON-serializable only.
- Do not persist raw NumPy arrays in metrics JSON.

## Team-Scoped Data Access

- Team context may be absent in non-request code paths.
- `for_team` manager returns empty queryset when context is missing (or raises in strict mode).
- Be explicit about context setup in tasks and background routines.

## Job Failure and Charging Behavior

- Analysis tasks use explicit failure handling that marks failed state and triggers refund logic.
- Keep updates to job status, cost, and timestamps atomic where possible.

## Frontend/Template Integration

- Vite-managed assets should be included with `django-vite` template tags.
- Use `static` tag for non-Vite static assets only.
- Favor HTMX and Alpine.js conventions already in the codebase over introducing new patterns.

## Documentation Practice

When shipping non-trivial behavior changes:

1. Update user-facing setup docs (`README.md`) only when usage changes.
2. Update architecture docs under `docs/architecture/` for implementation details.
3. Update agent guidance under `.claude/guides/` when conventions or operational patterns change.
