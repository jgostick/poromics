# Operations and Job Execution Guide

## Local Development Commands

- Initialize: `make init`
- Start services: `make start` or `make start-bg`
- Run app/dev pipeline: `make dev`
- Stop background services: `make stop`

## Celery and Background Work

- Celery app config: `poromics/celery.py`
- Main analysis tasks: `apps/pore_analysis/tasks.py`
- Scheduler: `django-celery-beat`

## Queue and Endpoint Routing

### Julia routing

- Queue map: `JULIA_BACKEND_QUEUE_MAP`
- Default endpoint: `JULIA_DEFAULT_SERVER_URL`
- Queue endpoint overrides: `JULIA_QUEUE_ENDPOINTS`

### Taichi routing

- Queue map: `TAICHI_BACKEND_QUEUE_MAP`
- Default endpoint: `TAICHI_DEFAULT_SERVER_URL`
- Queue endpoint overrides: `TAICHI_QUEUE_ENDPOINTS`

Routing intent:

- Keep queue names stable.
- Switch local vs remote execution by endpoint config.

## Remote Service Health

- Julia path currently enforces endpoint reachability in diffusivity task.
- Taichi path warns on health check failure and still attempts remote submit/poll.

## Safety and Environment

- Never overwrite `.env` without explicit confirmation.
- Current remote compute PoC assumes trusted LAN; auth/TLS are not enabled by default.

## Troubleshooting Checklist

1. Verify queue->endpoint env vars loaded in app process.
2. Confirm remote `/health` endpoint from the machine running workers.
3. Confirm worker is bound to the expected queue.
4. Inspect `AnalysisJob.parameters` for routing metadata.
5. Check refund/failure flow when remote execution fails.
