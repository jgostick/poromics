# Remote Python Analyses Guide

This guide explains how to:

1. Run the generic remote Python analysis server on a remote machine.
2. Run the matching Celery worker queue on the local Django machine.
3. Extend the pattern to additional analyses without creating bespoke transport layers.

## What This Uses

- Generic remote server: python_remote_server.py
- Generic remote client: python_remote_client.py
- Current first analysis on this path: pore-size (analysis_type = "poresize")
- Queue catalog source of truth: config/queues.yaml

## Runtime Contract

The generic server supports:

- GET /health
- GET /handlers
- POST /job
- GET /job/<job_id>
- DELETE /job/<job_id>

The client submits:

- analysis_type: string
- payload: JSON object

For pore-size, payload currently includes:

- image_npy_b64
- sizes
- voxel_size

## RunPod First Deployment (Pore Size)

Use this when you want the existing `poresize-remote` queue to execute on a RunPod endpoint.

## 1) Provision a RunPod endpoint

- Create a serverless endpoint (or pod + HTTP proxy) that exposes:
    - `GET /health`
    - `POST /job`
    - `GET /job/<job_id>`
    - `DELETE /job/<job_id>`
- Deploy `python_remote_server.py` in that environment.
- Ensure required Python packages are installed (`numpy`, `porespy`).

## 2) Set queue endpoint override in Render

Set the same env var on both web and celery services:

- `PYTHON_REMOTE_QUEUE_ENDPOINTS=poresize-remote=https://<RUNPOD_HOST>`

Optional default for all `compute_system=cpu` queues:

- `PYTHON_REMOTE_DEFAULT_SERVER_URL=https://<RUNPOD_HOST>`

Notes:

- Queue-specific overrides (`PYTHON_REMOTE_QUEUE_ENDPOINTS`) take precedence.
- Use the full HTTPS base URL with no trailing slash.

## 3) Deploy and smoke test

1. Redeploy web and celery.
2. Verify queue endpoint from app logs by launching a pore-size job on `poresize-remote`.
3. Confirm RunPod `/health` responds and jobs progress to completed.

## Remote Server Setup (Remote Machine)

## 1) Install dependencies

Two supported modes are available.

### Mode A: Full repo checkout on remote host

From repository root:

```bash
uv sync
```

If you are using an existing virtual environment:

```bash
source .venv/bin/activate
uv sync
```

### Mode B: Standalone server file on remote host

If the remote machine only has python_remote_server.py (no Django project code),
install the minimal runtime packages:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install numpy porespy
```

Notes:

- The server is now standalone and does not import apps.* modules.
- If porespy is missing, job execution returns an explicit package error.

## 2) Start the remote server

Default host/port are:

- PYTHON_REMOTE_SERVER_HOST=127.0.0.1
- PYTHON_REMOTE_SERVER_PORT=3100
- PYTHON_REMOTE_SERVER_WORKERS=2

For LAN access from your local Django host, bind to 0.0.0.0:

```bash
export PYTHON_REMOTE_SERVER_HOST=0.0.0.0
export PYTHON_REMOTE_SERVER_PORT=3100
export PYTHON_REMOTE_SERVER_WORKERS=2
export PYTHON_REMOTE_SERVER_LOG_LEVEL=INFO
python python_remote_server.py
```

## 3) Verify health from local Django machine

```bash
curl http://<REMOTE_HOST>:3100/health
```

Expected response shape:

```json
{"status":"ok","workers":2}
```

## Local Queue Setup (Local Django Machine)

The queue entry for pore-size remote is scaffolded in config/queues.yaml as:

- name: poresize-remote
- compute_system: cpu
- analyses: [poresize]
- endpoint_url: http://129.97.161.145:3100
- enabled: true

## Plugin loader environment variables

- PYTHON_REMOTE_HANDLER_MODULES: comma-separated plugin module list loaded at startup
- PYTHON_REMOTE_HANDLER_STRICT: when true, server startup fails if any plugin cannot be loaded

Example:

```bash
export PYTHON_REMOTE_HANDLER_MODULES=my_remote_plugins.network,my_remote_plugins.morphology
export PYTHON_REMOTE_HANDLER_STRICT=true
```

## 1) Enable/update queue in config/queues.yaml

Update the queue block for your environment:

- Set enabled: true
- Set endpoint_url to your remote server URL
- Keep analyses including poresize

If you are using environment overrides in Render, queue YAML can keep a placeholder/default endpoint.

Optional: make it the default queue for pore-size by changing analysis_defaults.poresize.

## 2) Start Celery worker for that queue

From local repository root:

```bash
uv run celery -A poromics worker -Q poresize-remote -n poresize-remote@%h --pool=solo -l INFO
```

Notes:

- The queue name in -Q must match config/queues.yaml.
- For additional remote analysis queues, run corresponding workers for each queue.

## 3) Run Django app

If not already running:

```bash
make dev
```

or:

```bash
uv run manage.py runserver
```

## End-to-End Validation

1. Confirm queue is enabled and endpoint_url is correct.
2. Confirm remote health endpoint returns 200.
3. Launch a pore-size job from the UI selecting the remote queue.
4. Confirm worker log shows task on poresize-remote.
5. Confirm final job status is completed and result payload is present.

## How To Extend To New Analyses

Use this pattern for each new Python-based analysis.

## 1) Add/keep a local compute function

In the analysis module, define a pure local compute function that returns a JSON-serializable dict.

Example pattern:

```python
def compute_new_analysis_solution(*, image_array, param_a, param_b) -> dict:
    ...
    return {"metric": value}
```

## 2) Add a dual-path runner in the analysis module

Add a wrapper that:

- Uses local compute when endpoint_url is empty.
- Uses python_remote_client submit/poll when endpoint_url is set.

Pattern:

```python
def run_new_analysis(*, image_array, param_a, endpoint_url: str | None = None) -> dict:
    if endpoint_url:
        # encode payload, submit_job, poll_job loop
        ...
    return compute_new_analysis_solution(...)
```

## 3) Register handler in python_remote_server.py

Use plugin modules so new analyses can be added without editing python_remote_server.py.

Each plugin module must expose:

- get_handlers() -> dict[str, callable]

Each mapping entry is:

- key: analysis_type string
- value: handler(payload: dict) -> dict

Pattern:

```python
def _handle_new_analysis(payload: dict) -> dict:
    # decode payload and compute
    ...
    return {"solution": solution}


def get_handlers() -> dict[str, callable]:
    return {
        "new_analysis": _handle_new_analysis,
    }
```

Then configure the server with your module path:

```bash
export PYTHON_REMOTE_HANDLER_MODULES=my_remote_plugins.new_analysis_plugin
export PYTHON_REMOTE_HANDLER_STRICT=true
python python_remote_server.py
```

You can verify loaded handlers via:

```bash
curl http://<REMOTE_HOST>:3100/handlers
```

Expected shape:

```json
{
  "status": "ok",
  "handlers": [
    {"analysis_type": "poresize", "source": "builtin:python_remote_server"},
    {"analysis_type": "new_analysis", "source": "plugin:my_remote_plugins.new_analysis_plugin"}
  ]
}
```

## 4) Update task to resolve endpoint and call dual-path runner

In apps/pore_analysis/tasks.py:

- Resolve queue from delivery_info via _get_task_queue_name.
- Resolve endpoint via _resolve_endpoint_for_job(..., compute="cpu") for generic Python remote queues.
- Pass endpoint_url into the analysis runner.

## 5) Update launch view to persist routing metadata

In apps/pore_analysis/views/image_analysis.py:

- Resolve endpoint from queue catalog.
- Save endpoint_url in job parameters via _with_routing_metadata.
- Optional preflight health check via python_remote_client._server_healthy.

## 6) Add queue catalog entries

In config/queues.yaml add queue entries for the new analysis:

- Unique queue name
- compute_system: cpu (for generic Python remote)
- analyses includes your new analysis type
- endpoint_url points at remote server
- enabled set per rollout stage
- pricing block configured

## 7) Add tests

At minimum add:

- Local solution payload shape test
- Remote submit/poll path test (mocked)
- Task endpoint resolution and fallback behavior test

## Queue Initialization Checklist (Per New Analysis)

1. Add/enable queue entry in config/queues.yaml.
2. Restart Django and Celery so queue catalog updates are loaded.
3. Start worker bound to that queue with -Q <queue_name>.
4. Confirm remote server has matching analysis_type handler.
5. Validate with one smoke job.

## Operational Notes

- This remote service currently assumes trusted network usage (no auth/TLS by default).
- Keep queue names stable and switch local/remote behavior by endpoint_url.
- Persisted endpoint_url in job parameters protects jobs during rollout when workers are not restarted immediately.

## Quick Commands Reference

Remote server:

```bash
export PYTHON_REMOTE_SERVER_HOST=0.0.0.0
export PYTHON_REMOTE_SERVER_PORT=3100
export PYTHON_REMOTE_SERVER_WORKERS=2
export PYTHON_REMOTE_HANDLER_MODULES=
export PYTHON_REMOTE_HANDLER_STRICT=false
python python_remote_server.py
```

Local Celery worker for pore-size remote queue:

```bash
uv run celery -A poromics worker -Q poresize-remote -n poresize-remote@%h --pool=solo -l INFO
```
