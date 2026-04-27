"""HTTP client for remote Taichi permeability worker service."""

import base64
import io
import logging
import os
from contextlib import suppress

import httpx
import numpy as np

log = logging.getLogger(__name__)

REQUEST_TIMEOUT_SECONDS = float(os.environ.get("TAICHI_REQUEST_TIMEOUT_SECONDS", "60.0"))
POLL_TIMEOUT_SECONDS = float(os.environ.get("TAICHI_POLL_TIMEOUT_SECONDS", "60.0"))
DELETE_TIMEOUT_SECONDS = float(os.environ.get("TAICHI_DELETE_TIMEOUT_SECONDS", "10.0"))


def _normalize_endpoint(endpoint_url: str | None) -> str:
    endpoint = (endpoint_url or "").strip().rstrip("/")
    return endpoint


def _encode_array(arr: np.ndarray) -> str:
    buf = io.BytesIO()
    np.save(buf, arr)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def submit_job(
    *,
    image_array: np.ndarray,
    direction: str,
    max_iterations: int,
    tolerance: float,
    backend: str,
    voxel_size: float,
    endpoint_url: str,
) -> str:
    endpoint = _normalize_endpoint(endpoint_url)
    if not endpoint:
        raise RuntimeError("Taichi endpoint is not configured.")

    payload = {
        "image_npy_b64": _encode_array(image_array.astype(bool)),
        "direction": direction,
        "max_iterations": int(max_iterations),
        "tolerance": float(tolerance),
        "backend": backend,
        "voxel_size": float(voxel_size),
    }

    response = httpx.post(f"{endpoint}/permeability", json=payload, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    data = response.json()
    job_id = data.get("job_id")
    if not isinstance(job_id, str) or not job_id:
        raise RuntimeError("Taichi server response did not include a valid job_id.")
    return job_id


def poll_job(*, job_id: str, endpoint_url: str) -> dict | None:
    endpoint = _normalize_endpoint(endpoint_url)
    try:
        response = httpx.get(f"{endpoint}/job/{job_id}", timeout=POLL_TIMEOUT_SECONDS)
    except httpx.TimeoutException:
        # Treat poll timeouts as transient and continue polling.
        log.warning("Timed out polling Taichi job %s at %s; continuing to wait", job_id, endpoint)
        return None
    response.raise_for_status()
    data = response.json()

    status = data.get("status")
    if status in {"pending", "running"}:
        return None
    if status == "error":
        raise RuntimeError(f"Taichi permeability job failed:\n{data.get('error', '(no details)')}")
    if status != "done":
        raise RuntimeError(f"Unexpected Taichi job status: {status}")

    solution = data.get("solution")
    if not isinstance(solution, dict):
        raise RuntimeError("Taichi server response missing 'solution' payload.")

    return solution


def cancel_job(*, job_id: str, endpoint_url: str) -> None:
    endpoint = _normalize_endpoint(endpoint_url)
    with suppress(Exception):
        httpx.delete(f"{endpoint}/job/{job_id}", timeout=DELETE_TIMEOUT_SECONDS)
