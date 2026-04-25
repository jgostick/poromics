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

### Generic Python remote (pore-size and future CPU remote analyses)

Configured in `poromics/settings.py`:

- `PYTHON_REMOTE_DEFAULT_SERVER_URL`: optional default endpoint for `compute_system=cpu` queues
- `PYTHON_REMOTE_QUEUE_ENDPOINTS`: optional per-queue endpoint overrides (`QUEUE=URL` pairs)

This supports routing queues such as `poresize-remote` to external services (for example RunPod)
without changing queue names.

## Task Resolution Flow

In `apps/pore_analysis/tasks.py`:

1. Resolve queue name from Celery task request delivery metadata.
2. Resolve endpoint for queue from settings.
3. Pass `endpoint_url` into the corresponding analysis module call.
4. Persist result and job lifecycle updates.

Functions involved:

- `_get_task_queue_name`
- `_resolve_julia_endpoint`
- `_resolve_taichi_endpoint`

## Local vs Remote Behavior

### Julia

- Diffusivity task currently enforces Julia health check before processing input.
- Failure to reach endpoint raises runtime error and triggers failure/refund flow.

### Taichi

- If endpoint is configured, task checks health and logs warning on failure, then still attempts submit/poll path.
- If endpoint is blank/unconfigured, analysis uses local in-process path.

#### Worker-driven RunPod wake-up (taichi-runpod)

- Permeability task flow now calls `maybe_ensure_runpod_pod` before Taichi remote health and submit.
- Wake behavior is settings-gated and queue-mapped:
	- `RUNPOD_WORKER_WAKE_ENABLED`
	- `RUNPOD_QUEUE_POD_IDS` (`queue=pod-id` pairs)
	- `RUNPOD_WAKE_TIMEOUT_SECONDS`
	- `RUNPOD_WAKE_POLL_INTERVAL_SECONDS`
- For mapped queues with remote endpoint routing, workers:
	1. inspect pod status,
	2. request pod start when needed,
	3. poll until `RUNNING` or timeout,
	4. then proceed with existing Taichi submit/poll logic.
- Current implementation is wake-only. Idle pause and terminate automation are intentionally out of scope.

## Service Interfaces

Remote clients:

- `julia_client.py`
- `taichi_client.py`

Remote servers:

- `julia_server.jl`
- `taichi_server.py`

Common pattern:

- health check
- submit job
- poll status
- collect result or error

## Security Posture (Current)

Current PoC setup assumes trusted LAN environment.

- No built-in auth at compute service layer
- No TLS termination in these services by default

If exposed beyond trusted network, add auth and transport security before production usage.
