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

`apps/pore_analysis/runpod_orchestration.py` now supports worker-side pod wake-up before remote dispatch.

Current scope:

- Wake behavior is enabled by settings.
- Queue-to-pod mapping is explicit (queue name -> RunPod pod id).
- Permeability tasks call this hook before Taichi health/submit when endpoint routing is remote.
- Pause/terminate automation remains disabled (wake-only behavior).

Required worker settings:

- `RUNPOD_WORKER_WAKE_ENABLED` (`true` or `false`)
- `RUNPOD_QUEUE_POD_IDS` (`queue=pod-id` pairs, comma-separated)
- `RUNPOD_WAKE_TIMEOUT_SECONDS` (default `300`)
- `RUNPOD_WAKE_POLL_INTERVAL_SECONDS` (default `5`)

Example:

```bash
RUNPOD_WORKER_WAKE_ENABLED=true
RUNPOD_QUEUE_POD_IDS=taichi-runpod=abc123podid
RUNPOD_WAKE_TIMEOUT_SECONDS=300
RUNPOD_WAKE_POLL_INTERVAL_SECONDS=5
```

Notes:

- If wake is disabled, queue mapping is missing, or endpoint routing is blank, the hook returns immediately.
- If pod wake does not reach `RUNNING` before timeout, task execution fails and follows existing retry/refund behavior.

### Runtime Queue Mapping from Dashboard (Non-Production)

Superusers can now map a RunPod pod to a RunPod queue from `/dashboard/site-admin/pods/`.

Behavior:

- Mapping stores queue + pod_id + endpoint_url in a database runtime override table.
- New jobs pick up runtime endpoint overrides without service restart.
- Worker wake-up resolves queue->pod_id from runtime mapping first, then `RUNPOD_QUEUE_POD_IDS` fallback.
- One queue maps to one pod and one pod maps to one queue.

Precedence for endpoint routing:

1. Runtime DB mapping (`RunPodQueueMapping.endpoint_url`)
2. Settings queue endpoint overrides (`*_QUEUE_ENDPOINTS`)
3. Queue catalog YAML endpoint (`config/queues.yaml`)
4. Default endpoint argument passed by caller

Operational note:

- This feature is intended for operator convenience in non-production workflows.
