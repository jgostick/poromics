"""Task-layer adapter for RunPod Serverless permeability jobs.

Resolves the endpoint ID for the taichi-runpod-serverless queue, encodes the image array
in the same base64-npy format used by taichi_client.py and taichi_serverless_handler.py,
submits the job, and polls until completion.

Input payload format (matches taichi_server.py and taichi_serverless_handler.py):
    image_npy_b64:  base64-encoded .npy file (bool array)
    direction:      "x" | "y" | "z"
    max_iterations: int
    tolerance:      float
    backend:        "cpu" | "gpu" | "cuda" | "metal" | "opengl"
    voxel_size:     float (metres per voxel)

Output (solution dict) format matches taichi_server.py _compute_permeability return value.
"""
from __future__ import annotations

import base64
import io
import logging

import numpy as np
from django.conf import settings

from apps.utils.runpod_pods import RunPodConfigurationError
from apps.utils.runpod_serverless import poll_until_done, submit_job

log = logging.getLogger(__name__)


def _resolve_serverless_endpoint_id(queue_name: str) -> str:
    """Return the RunPod Serverless endpoint ID for *queue_name*.

    Precedence:
    1. DB ``RunPodQueueMapping.endpoint_url`` (repurposed as endpoint_id for serverless).
    2. ``settings.RUNPOD_SERVERLESS_QUEUE_ENDPOINT_IDS[queue_name]``.

    Raises:
        RunPodConfigurationError: if neither source has an entry for *queue_name*.
    """
    # 1. Runtime DB override (endpoint_url field holds endpoint_id for serverless queues).
    try:
        from .queue_catalog import get_runtime_runpod_endpoint

        db_value = get_runtime_runpod_endpoint(queue_name)
        if db_value:
            return db_value.strip()
    except Exception:
        log.debug("Could not read runtime RunPod mapping for queue '%s'", queue_name, exc_info=True)

    # 2. Settings map.
    endpoint_ids: dict[str, str] = getattr(settings, "RUNPOD_SERVERLESS_QUEUE_ENDPOINT_IDS", {})
    endpoint_id = str(endpoint_ids.get(queue_name) or "").strip()
    if endpoint_id:
        return endpoint_id

    raise RunPodConfigurationError(
        f"No RunPod Serverless endpoint ID configured for queue '{queue_name}'. "
        "Set RUNPOD_SERVERLESS_QUEUE_ENDPOINT_IDS=taichi-runpod-serverless=<endpoint_id> "
        "or add a RunPodQueueMapping row for this queue."
    )


def _encode_array(arr: np.ndarray) -> str:
    buf = io.BytesIO()
    np.save(buf, arr.astype(bool))
    return base64.b64encode(buf.getvalue()).decode("ascii")


def run_permeability_serverless(
    *,
    queue_name: str,
    image_array: np.ndarray,
    direction: str,
    max_iterations: int,
    tolerance: float,
    backend: str,
    voxel_size: float,
) -> dict:
    """Submit a permeability job to the RunPod Serverless endpoint for *queue_name* and
    block until the result is available.

    Returns the solution dict (same shape as taichi_server.py _compute_permeability output).

    Raises:
        RunPodConfigurationError: if no endpoint ID is configured.
        RunPodAPIError: if the serverless job fails.
        RunPodTransientError: if the job times out or is cancelled.
    """
    endpoint_id = _resolve_serverless_endpoint_id(queue_name)

    payload = {
        "image_npy_b64": _encode_array(image_array),
        "direction": direction,
        "max_iterations": int(max_iterations),
        "tolerance": float(tolerance),
        "backend": backend,
        "voxel_size": float(voxel_size),
    }

    log.info(
        "Submitting permeability job to RunPod Serverless endpoint %s (queue=%s, direction=%s)",
        endpoint_id,
        queue_name,
        direction,
    )
    job_id = submit_job(endpoint_id, payload)
    return poll_until_done(endpoint_id, job_id)
