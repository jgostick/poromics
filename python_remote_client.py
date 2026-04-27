"""HTTP client for generic remote Python analysis workers."""

from __future__ import annotations

import base64
import io
import logging
from contextlib import suppress
import os

import httpx
import numpy as np

log = logging.getLogger(__name__)

REQUEST_TIMEOUT_SECONDS = float(os.environ.get("PYTHON_REMOTE_REQUEST_TIMEOUT_SECONDS", "60.0"))
POLL_TIMEOUT_SECONDS = float(os.environ.get("PYTHON_REMOTE_POLL_TIMEOUT_SECONDS", "60.0"))
DELETE_TIMEOUT_SECONDS = float(os.environ.get("PYTHON_REMOTE_DELETE_TIMEOUT_SECONDS", "10.0"))


def _normalize_endpoint(endpoint_url: str | None) -> str:
    return (endpoint_url or "").strip().rstrip("/")


def encode_array(arr: np.ndarray) -> str:
    buf = io.BytesIO()
    np.save(buf, arr, allow_pickle=False)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def decode_array(encoded_npy: str) -> np.ndarray:
    raw = base64.b64decode(encoded_npy)
    return np.load(io.BytesIO(raw), allow_pickle=False)


def submit_job(*, analysis_type: str, payload: dict, endpoint_url: str) -> str:
    endpoint = _normalize_endpoint(endpoint_url)
    if not endpoint:
        raise RuntimeError("Python remote endpoint is not configured.")

    response = httpx.post(
        f"{endpoint}/job",
        json={"analysis_type": analysis_type, "payload": payload},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    data = response.json()
    job_id = data.get("job_id")
    if not isinstance(job_id, str) or not job_id:
        raise RuntimeError("Python remote service response did not include a valid job_id.")
    return job_id


def poll_job(*, job_id: str, endpoint_url: str) -> dict | None:
    endpoint = _normalize_endpoint(endpoint_url)
    try:
        response = httpx.get(f"{endpoint}/job/{job_id}", timeout=POLL_TIMEOUT_SECONDS)
    except httpx.TimeoutException:
        log.warning("Timed out polling Python remote job %s at %s; continuing to wait", job_id, endpoint)
        return None

    response.raise_for_status()
    data = response.json()
    status = data.get("status")
    if status in {"pending", "running"}:
        return None
    if status == "error":
        raise RuntimeError(f"Python remote job failed:\n{data.get('error', '(no details)')}")
    if status != "done":
        raise RuntimeError(f"Unexpected Python remote job status: {status}")

    result = data.get("result")
    if not isinstance(result, dict):
        raise RuntimeError("Python remote service response missing 'result' payload.")
    return result


def cancel_job(*, job_id: str, endpoint_url: str) -> None:
    endpoint = _normalize_endpoint(endpoint_url)
    with suppress(Exception):
        httpx.delete(f"{endpoint}/job/{job_id}", timeout=DELETE_TIMEOUT_SECONDS)
