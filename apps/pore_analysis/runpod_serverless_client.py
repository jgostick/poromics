"""Task-layer adapter for RunPod Serverless permeability jobs.

Resolves the endpoint ID for the taichi-runpod-serverless queue, passes a presigned
storage URL for the image (to avoid RunPod's 10 MiB body limit), submits the job,
and polls until completion.

Input payload format (matches taichi_serverless_handler.py):
    image_url:      presigned S3 URL pointing to the .npy image file
    direction:      "x" | "y" | "z"
    max_iterations: int
    tolerance:      float
    backend:        "cpu" | "gpu" | "cuda" | "metal" | "opengl"
    voxel_size:     float (metres per voxel)

Output (solution dict) format matches taichi_server.py _compute_permeability return value.
"""
from __future__ import annotations

import logging

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


def run_permeability_serverless(
    *,
    queue_name: str,
    image_url: str,
    direction: str,
    max_iterations: int,
    tolerance: float,
    backend: str,
    voxel_size: float,
) -> dict:
    """Submit a permeability job to the RunPod Serverless endpoint for *queue_name* and
    block until the result is available.

    The worker downloads the image directly from *image_url* (a presigned S3 URL),
    bypassing RunPod's 10 MiB request body limit.

    Returns the solution dict (same shape as taichi_server.py _compute_permeability output).

    Raises:
        RunPodConfigurationError: if no endpoint ID is configured.
        RunPodAPIError: if the serverless job fails.
        RunPodTransientError: if the job times out or is cancelled.
    """
    endpoint_id = _resolve_serverless_endpoint_id(queue_name)

    payload = {
        "image_url": image_url,
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
