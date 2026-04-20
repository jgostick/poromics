"""
Python client for the Julia tortuosity HTTP server (julia_server.jl).

The server is a long-running Julia process that keeps Tortuosity.jl and CUDA
warm.  Compilation happens once at server startup; subsequent requests are fast.

Public API
----------
ensure_server_running()
    Start the Julia server if it is not already listening.  Safe to call on
    every Streamlit rerun — it returns immediately if the server is up.

available_backends() -> list[str]
    Return the DNS backend options supported by the Julia server on this
    machine.  Always includes "cpu" and includes "gpu" only when CUDA GPUs are
    available to the server.

submit_job(img, axis, reltol, use_gpu, D=None) -> job_id: str
    Submit a Bool image (and optional Float32 diffusivity map D) for tortuosity
    calculation.  Returns immediately with a job ID string; the calculation runs
    in the background on the Julia server.

poll_job(job_id) -> None | tuple[float, np.ndarray]
    Check the status of a submitted job.
    Returns None if the job is still pending/running.
    Returns (tau, conc) when done.
    Raises RuntimeError if the job failed.

cancel_job(job_id)
    Cancel and remove a job from the server (best-effort).
"""

import io
import logging
import os
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx
import numpy as np

log = logging.getLogger(__name__)

SERVER_HOST = os.environ.get("JULIA_SERVER_HOST", "127.0.0.1")
SERVER_PORT = int(os.environ.get("JULIA_SERVER_PORT", "2999"))
DEFAULT_SERVER_URL = os.environ.get("JULIA_DEFAULT_SERVER_URL", f"http://{SERVER_HOST}:{SERVER_PORT}")
STARTUP_TIMEOUT = 600  # seconds — Julia warmup can take several minutes on first run

_server_proc: subprocess.Popen | None = None


def _resolve_server_url(endpoint_url: str | None = None) -> str:
    return endpoint_url or DEFAULT_SERVER_URL


def _is_local_endpoint(endpoint_url: str) -> bool:
    try:
        parsed = urlparse(endpoint_url)
    except Exception:
        return False
    return parsed.hostname in {"127.0.0.1", "localhost", "::1"}


def _endpoint_host_port(endpoint_url: str) -> tuple[str, int]:
    parsed = urlparse(endpoint_url)
    host = parsed.hostname or SERVER_HOST
    port = parsed.port or SERVER_PORT
    return host, int(port)


def _server_healthy(endpoint_url: str | None = None) -> bool:
    server_url = _resolve_server_url(endpoint_url)
    try:
        r = httpx.get(f"{server_url}/health", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


def _server_health(endpoint_url: str | None = None) -> dict:
    server_url = _resolve_server_url(endpoint_url)
    try:
        resp = httpx.get(f"{server_url}/health", timeout=2.0)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {"status": "unavailable", "gpus": 0}


def ensure_server_running(endpoint_url: str | None = None) -> None:
    """Start the Julia server if it is not already listening.

    Safe to call repeatedly — returns immediately if the server is up.
    Blocks (with a progress message) until Julia finishes its warmup.
    """
    global _server_proc
    server_url = _resolve_server_url(endpoint_url)

    if _server_healthy(server_url):
        return

    if not _is_local_endpoint(server_url):
        raise RuntimeError(f"Remote Julia server is unreachable at {server_url}.")

    server_host, server_port = _endpoint_host_port(server_url)

    project_root = Path(__file__).parent
    server_script = project_root / "julia_server.jl"

    # Resolve the Julia executable via juliapkg so we use the same version as
    # the rest of the project, without requiring Julia on PATH.
    import juliapkg
    julia_exe  = juliapkg.executable()
    project_dir = juliapkg.project()
    local_depot = project_root / ".julia_depot"

    env = {
        **os.environ,
        "JULIA_DEPOT_PATH": str(local_depot),
        "JULIA_SERVER_HOST": server_host,
        "JULIA_SERVER_PORT": str(server_port),
        # Strip system CUDA paths so CUDA.jl uses its own bundled libraries.
        "LD_LIBRARY_PATH": ":".join(
            p for p in os.environ.get("LD_LIBRARY_PATH", "").split(":")
            if "cuda" not in p.lower()
        ),
        "JULIA_CUDA_SOFT_FAIL": "true",
    }

    log.info("Starting Julia tortuosity server (this takes a few minutes on first run)…")

    # Use a precompiled sysimage if one exists — this cuts server startup from
    # several minutes (cold JIT) down to ~5-10 seconds (loading pre-compiled code).
    # The sysimage is optional: without it Julia still starts correctly, it just
    # takes longer on the first launch because it JIT-compiles Tortuosity + CUDA.
    sysimage_path = Path(project_dir) / "tortuosity.so"
    julia_cmd = [julia_exe, "--startup-file=no", f"--project={project_dir}"]
    if sysimage_path.exists():
        julia_cmd += [f"--sysimage={sysimage_path}"]
        log.info(f"Using sysimage: {sysimage_path}")
    else:
        log.info("No sysimage found — startup will be slow (Julia JIT compiling).")
    julia_cmd.append(str(server_script))

    _server_proc = subprocess.Popen(
        julia_cmd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,  # merge so logs appear together
        text=True,
    )

    # Wait for the server to become healthy.
    deadline = time.monotonic() + STARTUP_TIMEOUT
    while time.monotonic() < deadline:
        # Check if the process died immediately (bad config, missing package…)
        ret = _server_proc.poll()
        if ret is not None:
            out = _server_proc.stdout.read() if _server_proc.stdout else ""
            raise RuntimeError(
                f"Julia server exited with code {ret} before becoming ready.\n{out}"
            )
        if _server_healthy(server_url):
            log.info("Julia tortuosity server is ready.")
            return
        time.sleep(2)

    raise RuntimeError(
        f"Julia server did not become healthy within {STARTUP_TIMEOUT}s."
    )


def available_backends(endpoint_url: str | None = None) -> list[str]:
    """Return DNS backend options supported by the Julia server."""
    ensure_server_running(endpoint_url)
    health = _server_health(endpoint_url)
    options = ["cpu"]
    if int(health.get("gpus", 0) or 0) > 0:
        options.append("gpu")
    return options


def submit_job(
    img: np.ndarray,
    axis: str,
    reltol: float,
    use_gpu: bool,
    D: np.ndarray | None = None,
    endpoint_url: str | None = None,
) -> str:
    """Submit an image for tortuosity calculation.  Returns a job ID immediately.

    Parameters
    ----------
    img : np.ndarray
        3-D boolean array (the pore-space domain).
    D : np.ndarray, optional
        3-D float32 array of per-voxel diffusivity values, same shape as img.
        Omit for the standard binary case (all open voxels treated equally).
    """
    buf = io.BytesIO()
    np.save(buf, img.astype(bool))
    buf.seek(0)

    files: dict = {
        "image":  ("image.npy", buf, "application/octet-stream"),
        "axis":   (None, axis),
        "reltol": (None, str(reltol)),
        "gpu":    (None, str(use_gpu).lower()),
    }
    if D is not None:
        dbuf = io.BytesIO()
        np.save(dbuf, D.astype(np.float32))
        dbuf.seek(0)
        files["D"] = ("D.npy", dbuf, "application/octet-stream")

    ensure_server_running(endpoint_url)
    server_url = _resolve_server_url(endpoint_url)

    resp = httpx.post(
        f"{server_url}/tortuosity",
        files=files,
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()["job_id"]


def poll_job(job_id: str, endpoint_url: str | None = None) -> tuple | None:
    """Poll a job.  Returns None if still running, or (tau, conc) when done.

    Raises RuntimeError on server-side failure.
    """
    server_url = _resolve_server_url(endpoint_url)
    resp = httpx.get(f"{server_url}/job/{job_id}", timeout=10.0)
    resp.raise_for_status()
    data = resp.json()

    status = data["status"]
    if status in ("pending", "running"):
        return None
    if status == "error":
        raise RuntimeError(f"Julia tortuosity job failed:\n{data.get('error', '(no details)')}")

    # status == "done" — fetch the concentration field
    tau = float(data["tau"])
    conc_resp = httpx.get(f"{server_url}/job/{job_id}/conc", timeout=30.0)
    conc_resp.raise_for_status()
    conc = np.load(io.BytesIO(conc_resp.content))["conc"]

    # Clean up the job from the server store
    cancel_job(job_id, endpoint_url=endpoint_url)
    return tau, conc


def cancel_job(job_id: str, endpoint_url: str | None = None) -> None:
    """Cancel / remove a job from the server (best-effort, ignores errors)."""
    server_url = _resolve_server_url(endpoint_url)
    try:
        httpx.delete(f"{server_url}/job/{job_id}", timeout=5.0)
    except Exception:
        pass
