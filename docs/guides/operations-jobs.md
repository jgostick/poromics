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

## RunPod Pod Controls (Site Admin)

Site Admin now includes a Pods tab for superusers at `/dashboard/site-admin/pods/`.

Supported actions:

- List pods
- Create pod
- Pause pod (`stop`)
- Resume pod (`start`)
- Terminate pod (`delete`)

The dashboard does not call RunPod directly. It uses the shared service module in `apps/utils/runpod_pods.py`.

### Required Settings

- `RUNPOD_API_BASE_URL` (default `https://rest.runpod.io/v1`)
- `RUNPOD_API_KEY`
- `RUNPOD_DEFAULT_CLOUD_TYPE`
- `RUNPOD_DEFAULT_COMPUTE_TYPE`
- `RUNPOD_DEFAULT_PORTS` (comma-separated list, e.g. `8888/http,22/tcp`)
- `RUNPOD_REGISTRY_AUTH_ID` (optional)
- `RUNPOD_REGISTRY_USERNAME` (optional fallback)
- `RUNPOD_REGISTRY_PAT` (optional fallback)

Timeout/retry knobs:

- `RUNPOD_CONNECT_TIMEOUT_SECONDS`
- `RUNPOD_HTTP_TIMEOUT_SECONDS`
- `RUNPOD_RETRY_COUNT`
- `RUNPOD_RETRY_BACKOFF_SECONDS`
- `RUNPOD_OPTIONS_CACHE_TTL_SECONDS`
- `RUNPOD_IDEMPOTENCY_TTL_SECONDS`

### Shared Service Contract (Dashboard and Workers)

The reusable API for callers is:

- `list_pods()`
- `get_creation_options(force_refresh=False)`
- `create_pod(spec, idempotency_key=None)`
- `pause_pod(pod_id)`
- `resume_pod(pod_id)`
- `terminate_pod(pod_id)`

Programmatic helper wrappers for future worker orchestration are also provided:

- `ensure_pod_exists(spec, idempotency_key=None)`
- `pause_idle_pod(pod_id)`
- `terminate_broken_pod(pod_id)`

Typed exceptions for normalized error handling:

- `RunPodConfigurationError`
- `RunPodAuthError`
- `RunPodValidationError`
- `RunPodCapacityError`
- `RunPodTransientError`
- `RunPodNotFoundError`
- `RunPodAPIError`

### Current Celery Integration Seam

`apps/pore_analysis/runpod_orchestration.py` defines an intentionally no-op hook that is called by CPU task paths.
This preserves current routing behavior while establishing a stable integration point for later autoscaling work.
