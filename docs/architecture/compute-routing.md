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
