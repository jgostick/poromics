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

Taichi permeability has three execution paths selected by `backend_key` in `config/queues.yaml`:

| Queue | `backend_key` | Behavior |
|---|---|---|
| `kabs-cpu` | `cpu` | Local in-process Taichi |
| `taichi-runpod-pod` | `runpod-gpu` | Ephemeral RunPod pod (created fresh per job, terminated after) |
| `taichi-runpod-serverless` | `serverless` | RunPod Serverless endpoint |

Routing intent: keep queue names stable; switch local vs remote execution by `backend_key` and endpoint config.

## Remote Service Health

- Julia path enforces endpoint reachability before each diffusivity job (persistent server — meaningful preflight guard).
- Taichi pod and serverless paths do not perform a pre-flight health check; RunPod manages availability.

## Safety and Environment

- Never overwrite `.env` without explicit confirmation.
- Current remote compute PoC assumes trusted LAN; auth/TLS are not enabled by default.

## Troubleshooting Checklist

1. Verify queue->endpoint env vars are loaded in the app process.
2. Confirm remote `/health` endpoint is reachable from the machine running workers (Julia only).
3. Confirm worker is bound to the expected queue.
4. Inspect `AnalysisJob.parameters` for routing metadata.
5. Check refund/failure flow when remote execution fails.

## RunPod Pod Controls (Site Admin)

Site Admin includes a Pods tab for superusers at `/dashboard/site-admin/pods/`.

Supported actions:

- List pods
- Create pod
- Pause pod (`stop`)
- Resume pod (`start`)
- Terminate pod (`delete`)

The dashboard uses the shared service module in `apps/utils/runpod_pods.py`.

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

The reusable API in `apps/utils/runpod_pods.py`:

- `list_pods()`
- `get_creation_options(force_refresh=False)`
- `create_pod(spec, idempotency_key=None)`
- `pause_pod(pod_id)`
- `resume_pod(pod_id)`
- `terminate_pod(pod_id)`

Typed exceptions for normalized error handling:

- `RunPodConfigurationError`
- `RunPodAuthError`
- `RunPodValidationError`
- `RunPodCapacityError`
- `RunPodTransientError`
- `RunPodNotFoundError`
- `RunPodAPIError`

## RunPod Ephemeral Pod Orchestration (`taichi-runpod-pod`)

`apps/pore_analysis/runpod_orchestration.py` manages ephemeral pod lifecycle for the `taichi-runpod-pod` queue.

Behavior:

- `create_ephemeral_pod(queue_name)` creates a fresh pod from `RUNPOD_POD_QUEUE_SPECS` and waits for it to be healthy.
- `terminate_ephemeral_pod(pod_id)` terminates the pod immediately after the job completes (called in a `finally` block).
- Pods are named with the prefix `taichi-ephemeral-` for orphan detection.

### Required Worker Settings

- `RUNPOD_POD_QUEUE_SPECS`: JSON dict mapping queue name to pod spec, e.g.:
  ```json
  {"taichi-runpod-pod": {"image_name": "myregistry/taichi-worker:latest", "gpu_type_id": "NVIDIA GeForce RTX 3090", "cloud_type": "SECURE"}}
  ```
- `RUNPOD_POD_TAICHI_PORT`: port the Taichi HTTP server listens on inside the pod (default `8888`)
- `RUNPOD_POD_STARTUP_TIMEOUT_SECONDS`: how long to wait for pod health before failing (default `300`)
- `RUNPOD_POD_STARTUP_POLL_INTERVAL_SECONDS`: health poll interval during startup (default `5`)
- `RUNPOD_POD_MAX_AGE_SECONDS`: pods older than this are treated as orphaned (default `3600`)

### Orphaned Pod Cleanup

A Celery Beat task `cleanup_orphaned_ephemeral_pods` periodically scans for and terminates pods that:

1. Have names starting with `taichi-ephemeral-`
2. Are older than `RUNPOD_POD_MAX_AGE_SECONDS`

Schedule this task via `django-celery-beat` or `SCHEDULED_TASKS` in settings. Recommended interval: every 30 minutes.

## RunPod Serverless (`taichi-runpod-serverless`)

`apps/utils/runpod_serverless.py` is the REST client for the RunPod Serverless API.
`apps/pore_analysis/runpod_serverless_client.py` is the task-layer adapter.
`taichi_serverless_handler.py` (repo root) is the handler deployed to RunPod.

### Required Worker Settings

- `RUNPOD_SERVERLESS_API_BASE_URL`: RunPod Serverless API base (default `https://api.runpod.ai/v2`)
- `RUNPOD_SERVERLESS_QUEUE_ENDPOINT_IDS`: JSON dict mapping queue name to endpoint ID, e.g.:
  ```json
  {"taichi-runpod-serverless": "abc123endpointid"}
  ```
- `RUNPOD_SERVERLESS_JOB_TIMEOUT_SECONDS`: max polling duration (default `600`)
- `RUNPOD_SERVERLESS_POLL_INTERVAL_SECONDS`: poll interval (default `5`)

Endpoint ID resolution order:

1. `RunPodQueueMapping.endpoint_url` (DB, set via `/dashboard/site-admin/pods/`)
2. `RUNPOD_SERVERLESS_QUEUE_ENDPOINT_IDS` settings dict

### Deploying the Serverless Handler

Build and push a Docker image containing `taichi_serverless_handler.py` and its dependencies.
Deploy as a RunPod Serverless endpoint. Set the resulting endpoint ID in `RUNPOD_SERVERLESS_QUEUE_ENDPOINT_IDS`.

## Runtime Queue Mapping from Dashboard

Superusers can map a RunPod pod or serverless endpoint to a queue from `/dashboard/site-admin/pods/`.

- For pod-type queues: stores queue + pod_id + endpoint URL.
- For serverless queues: stores queue + endpoint_id in the `endpoint_url` field.
- New jobs pick up runtime overrides without service restart.
- One queue maps to one mapping record.

Endpoint routing precedence:

1. Runtime DB mapping (`RunPodQueueMapping.endpoint_url`)
2. Settings queue endpoint overrides (`*_QUEUE_ENDPOINTS`)
3. Queue catalog YAML endpoint (`config/queues.yaml`)
4. Default endpoint argument passed by caller
