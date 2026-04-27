# Compute Routing: Julia and Taichi

This document describes how analysis jobs are routed between local and remote compute services.

## Design Goal

Keep Celery queue names stable while selecting local vs remote execution by endpoint configuration.

## Settings-Driven Routing

### Julia (diffusivity)

Configured in `poromics/settings.py`:

- `JULIA_BACKEND_QUEUE_MAP`: backend -> queue name
- `JULIA_DEFAULT_SERVER_URL`: fallback endpoint
- `JULIA_QUEUE_ENDPOINTS`: optional per-queue endpoint overrides (`QUEUE=URL` pairs)

Helper behavior:

- Queue/endpoint pairs are parsed by `_parse_queue_endpoint_pairs`.
- Standard Julia queues are ensured in `JULIA_QUEUE_ENDPOINTS` with default fallback.

### Taichi (permeability)

Configured in `poromics/settings.py`:

- `TAICHI_BACKEND_QUEUE_MAP`: backend -> queue name
- `TAICHI_DEFAULT_SERVER_URL`: optional default endpoint (empty means local execution)
- `TAICHI_QUEUE_ENDPOINTS`: optional per-queue endpoint overrides

If `TAICHI_DEFAULT_SERVER_URL` is set, queues without explicit overrides inherit it.

Taichi permeability supports three execution paths, selected by the `backend_key` of the dispatched queue:

| `backend_key` | Queue name | Behavior |
|---|---|---|
| `cpu` / (default) | `kabs-cpu` | In-process Taichi (local) |
| `runpod-gpu` | `taichi-runpod-pod` | Ephemeral RunPod pod — created fresh per job, terminated after |
| `serverless` | `taichi-runpod-serverless` | RunPod Serverless — endpoint managed by RunPod |

### Generic Python remote (pore-size and future CPU remote analyses)

Configured in `poromics/settings.py`:

- `PYTHON_REMOTE_DEFAULT_SERVER_URL`: optional default endpoint for `compute_system=cpu` queues
- `PYTHON_REMOTE_QUEUE_ENDPOINTS`: optional per-queue endpoint overrides (`QUEUE=URL` pairs)

This supports routing queues such as `poresize-remote` to external services (for example RunPod)
without changing queue names.

## Task Resolution Flow

In `apps/pore_analysis/tasks.py`:

1. Resolve queue name from Celery task request delivery metadata.
2. Check queue `backend_key` via `_is_serverless_queue` / `_is_runpod_pod_queue`.
3. Execute on the matching path (serverless, ephemeral pod, or local).
4. Persist result and job lifecycle updates.

Functions involved:

- `_get_task_queue_name`
- `_is_serverless_queue`
- `_is_runpod_pod_queue`
- `_resolve_julia_endpoint`
- `_resolve_taichi_endpoint`

Endpoint precedence for `get_queue_endpoint`:

1. Runtime DB mapping (`RunPodQueueMapping.endpoint_url`)
2. Settings override maps (`JULIA_QUEUE_ENDPOINTS`, `TAICHI_QUEUE_ENDPOINTS`, `PYTHON_REMOTE_QUEUE_ENDPOINTS`)
3. Queue catalog endpoint (`config/queues.yaml`)
4. Default value provided by caller

## Local vs Remote Behavior

### Julia

- Diffusivity task enforces a Julia health check before processing input.
- Failure to reach endpoint raises runtime error and triggers failure/refund flow.
- Julia runs as a persistent always-on server; the health check is intentional.

### Taichi — Local / CPU

- If endpoint is blank/unconfigured, analysis uses local in-process Taichi path.

### Taichi — Ephemeral RunPod Pod (`taichi-runpod-pod`)

- Worker creates a **fresh pod** via `create_ephemeral_pod(queue_name)` at job start.
- Pod spec is resolved from `RUNPOD_POD_QUEUE_SPECS` (settings) keyed by queue name.
- Pod URL format: `https://{pod_id}-{port}.proxy.runpod.net`
- After computation, `terminate_ephemeral_pod(pod_id)` is called in a `finally` block to
  ensure termination even on failure.
- Pods are named with `EPHEMERAL_POD_NAME_PREFIX = "taichi-ephemeral-"` for orphan detection.
- Relevant settings in `poromics/settings.py`:
  - `RUNPOD_POD_QUEUE_SPECS`: per-queue pod spec dicts (image, GPU type, etc.)
  - `RUNPOD_POD_TAICHI_PORT`: HTTP port exposed by Taichi server on the pod
  - `RUNPOD_POD_STARTUP_TIMEOUT_SECONDS`: how long to wait for pod to become healthy
  - `RUNPOD_POD_STARTUP_POLL_INTERVAL_SECONDS`: health poll interval during startup
  - `RUNPOD_POD_MAX_AGE_SECONDS`: max pod age for orphaned-pod cleanup (default 3600)

#### Orphaned pod cleanup

A Celery Beat task `cleanup_orphaned_ephemeral_pods` periodically calls
`terminate_orphaned_ephemeral_pods()` from `apps/pore_analysis/runpod_orchestration.py`.
It terminates any pod whose name starts with `taichi-ephemeral-` and whose age exceeds
`RUNPOD_POD_MAX_AGE_SECONDS`. This guards against pods left running when a worker is killed
before the `finally` block executes.

### Taichi — RunPod Serverless (`taichi-runpod-serverless`)

- RunPod manages worker lifecycle entirely; no pod creation or endpoint URL is needed.
- Task delegates to `run_permeability_serverless(...)` in `apps/pore_analysis/runpod_serverless_client.py`.
- Endpoint ID is resolved from:
  1. `RunPodQueueMapping.endpoint_url` (DB, keyed by queue name)
  2. `RUNPOD_SERVERLESS_QUEUE_ENDPOINT_IDS` settings dict
- The REST client lives in `apps/utils/runpod_serverless.py` (submit → poll → result).
- The serverless handler deployed to RunPod is `taichi_serverless_handler.py` (repo root).
- Relevant settings:
  - `RUNPOD_SERVERLESS_API_BASE_URL`: base URL for RunPod Serverless REST API
  - `RUNPOD_SERVERLESS_QUEUE_ENDPOINT_IDS`: `{queue_name: endpoint_id}` dict
  - `RUNPOD_SERVERLESS_JOB_TIMEOUT_SECONDS`: max polling duration
  - `RUNPOD_SERVERLESS_POLL_INTERVAL_SECONDS`: poll interval

#### Runtime mapping UI

- Superusers can update `RunPodQueueMapping` from `/dashboard/site-admin/pods/`.
- For serverless queues the `endpoint_url` column stores the RunPod endpoint ID.
- Supported scope is RunPod-named queues (for example `taichi-runpod-pod`, `taichi-runpod-serverless`).

## Service Interfaces

Remote clients:

- `julia_client.py`
- `taichi_client.py`
- `apps/utils/runpod_serverless.py`

Remote servers:

- `julia_server.jl`
- `taichi_server.py` (pod-based)
- `taichi_serverless_handler.py` (serverless)

Common pod/serverless pattern:

- submit job
- poll status
- collect result or error

Julia additionally performs a health check before submission (persistent server).

## Security Posture (Current)

Current PoC setup assumes trusted LAN environment.

- No built-in auth at compute service layer
- No TLS termination in these services by default

If exposed beyond trusted network, add auth and transport security before production usage.
