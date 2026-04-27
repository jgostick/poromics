"""RunPod Serverless REST API client.

Wraps the RunPod Serverless v2 API (https://api.runpod.ai/v2) for submitting jobs to
serverless endpoints and polling their status.  Authentication reuses RUNPOD_API_KEY.

RunPod Serverless API reference:
  POST /v2/{endpoint_id}/run           — async submit, returns {"id": job_id, "status": ...}
  GET  /v2/{endpoint_id}/status/{id}   — poll status
  POST /v2/{endpoint_id}/cancel/{id}   — cancel a queued or running job

Job status values returned by RunPod:
  IN_QUEUE      — waiting for a worker
  IN_PROGRESS   — worker picked it up
  COMPLETED     — done, output field is populated
  FAILED        — worker error, error field is populated
  CANCELLED     — cancelled by caller
  TIMED_OUT     — RunPod internal timeout
"""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx
from django.conf import settings

from apps.utils.runpod_pods import RunPodAPIError, RunPodAuthError, RunPodConfigurationError, RunPodTransientError

log = logging.getLogger(__name__)

_TERMINAL_STATUSES = {"COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"}


def _api_base_url() -> str:
    return str(getattr(settings, "RUNPOD_SERVERLESS_API_BASE_URL", "https://api.runpod.ai/v2")).rstrip("/")


def _api_key() -> str:
    key = str(getattr(settings, "RUNPOD_API_KEY", "") or "")
    if not key:
        raise RunPodConfigurationError("RUNPOD_API_KEY is not set — cannot call RunPod Serverless API.")
    return key


def _connect_timeout() -> float:
    return float(getattr(settings, "RUNPOD_CONNECT_TIMEOUT_SECONDS", 10.0))


def _http_timeout() -> float:
    return float(getattr(settings, "RUNPOD_HTTP_TIMEOUT_SECONDS", 30.0))


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_api_key()}", "Content-Type": "application/json"}


def _request(method: str, url: str, *, json: Any = None) -> dict:
    """Make a single authenticated request and return the parsed JSON body.

    Raises typed RunPod exceptions rather than raw httpx errors.
    """
    timeout = httpx.Timeout(connect=_connect_timeout(), read=_http_timeout(), write=_http_timeout(), pool=5.0)
    try:
        response = httpx.request(method, url, headers=_headers(), json=json, timeout=timeout)
    except httpx.TimeoutException as exc:
        raise RunPodTransientError(f"Request to RunPod Serverless timed out: {url}") from exc
    except httpx.RequestError as exc:
        raise RunPodTransientError(f"Network error calling RunPod Serverless ({url}): {exc}") from exc

    if response.status_code == 401:
        raise RunPodAuthError("RunPod Serverless returned 401 — check RUNPOD_API_KEY.")
    if response.status_code == 429:
        raise RunPodTransientError("RunPod Serverless rate limit hit (429).")
    if response.status_code >= 500:
        raise RunPodTransientError(
            f"RunPod Serverless returned {response.status_code}: {response.text[:200]}"
        )
    if response.status_code >= 400:
        raise RunPodAPIError(
            f"RunPod Serverless returned {response.status_code}: {response.text[:200]}",
            status_code=response.status_code,
        )

    try:
        return response.json()
    except Exception as exc:
        raise RunPodAPIError(f"RunPod Serverless returned non-JSON body: {response.text[:200]}") from exc


def submit_job(endpoint_id: str, payload: dict) -> str:
    """Submit *payload* to RunPod Serverless endpoint *endpoint_id*.

    Returns the RunPod job id string.

    Args:
        endpoint_id: RunPod Serverless endpoint ID (from dashboard, e.g. ``"abc123xyz"``).
        payload: Dict sent as the ``input`` field of the RunPod job body.

    Raises:
        RunPodConfigurationError: if RUNPOD_API_KEY is missing.
        RunPodAuthError: on 401.
        RunPodTransientError: on network / rate-limit / 5xx errors.
        RunPodAPIError: on other 4xx errors.
    """
    url = f"{_api_base_url()}/{endpoint_id}/run"
    log.debug("Submitting RunPod Serverless job to endpoint %s", endpoint_id)
    data = _request("POST", url, json={"input": payload})
    job_id = str(data.get("id") or "").strip()
    if not job_id:
        raise RunPodAPIError(
            f"RunPod Serverless submit response did not include a job id: {data}"
        )
    log.info("RunPod Serverless job %s submitted to endpoint %s", job_id, endpoint_id)
    return job_id


def poll_status(endpoint_id: str, job_id: str) -> dict:
    """Poll the status of RunPod Serverless job *job_id*.

    Returns the full status dict from the API, e.g.::

        {
            "id": "...",
            "status": "COMPLETED" | "FAILED" | "IN_QUEUE" | "IN_PROGRESS" | ...,
            "output": {...},   # present when COMPLETED
            "error": "...",    # present when FAILED
        }

    Raises:
        RunPodTransientError: on network / rate-limit / 5xx errors.
        RunPodAPIError: on other 4xx errors.
    """
    url = f"{_api_base_url()}/{endpoint_id}/status/{job_id}"
    return _request("GET", url)


def cancel_job(endpoint_id: str, job_id: str) -> None:
    """Cancel a queued or running RunPod Serverless job.

    Errors are logged but not re-raised so this is safe to call from cleanup paths.
    """
    url = f"{_api_base_url()}/{endpoint_id}/cancel/{job_id}"
    try:
        _request("POST", url)
        log.info("Cancelled RunPod Serverless job %s on endpoint %s", job_id, endpoint_id)
    except Exception:
        log.warning(
            "Failed to cancel RunPod Serverless job %s on endpoint %s",
            job_id,
            endpoint_id,
            exc_info=True,
        )


def poll_until_done(endpoint_id: str, job_id: str) -> dict:
    """Block until RunPod Serverless job *job_id* reaches a terminal state.

    Returns the ``output`` dict on success.

    Raises:
        RunPodTransientError: if the job does not finish within the configured timeout, or
            if RunPod itself reports TIMED_OUT or CANCELLED.
        RunPodAPIError: if the job FAILED (error message included).
    """
    timeout = float(getattr(settings, "RUNPOD_SERVERLESS_JOB_TIMEOUT_SECONDS", 600.0))
    poll_interval = float(getattr(settings, "RUNPOD_SERVERLESS_POLL_INTERVAL_SECONDS", 5.0))
    deadline = time.monotonic() + timeout

    while True:
        now = time.monotonic()
        if now >= deadline:
            log.warning("Timed out waiting for RunPod Serverless job %s; attempting cancel", job_id)
            cancel_job(endpoint_id, job_id)
            raise RunPodTransientError(
                f"RunPod Serverless job {job_id} did not complete within {timeout:.0f}s."
            )

        try:
            status_data = poll_status(endpoint_id, job_id)
        except RunPodTransientError as exc:
            # 5xx / network errors during cold-start or transient gateway issues —
            # keep waiting rather than failing the job immediately.
            log.warning(
                "Transient error polling RunPod Serverless job %s (will retry): %s",
                job_id,
                exc,
            )
            time.sleep(min(poll_interval, max(0.0, deadline - time.monotonic())))
            continue

        status = str(status_data.get("status") or "").upper()

        if status == "COMPLETED":
            output = status_data.get("output")
            if not isinstance(output, dict):
                raise RunPodAPIError(
                    f"RunPod Serverless job {job_id} completed but returned no output dict: {status_data}"
                )
            log.info("RunPod Serverless job %s COMPLETED", job_id)
            return output

        if status == "FAILED":
            error_msg = str(status_data.get("error") or "(no details)")
            raise RunPodAPIError(f"RunPod Serverless job {job_id} FAILED: {error_msg}")

        if status in ("CANCELLED", "TIMED_OUT"):
            raise RunPodTransientError(
                f"RunPod Serverless job {job_id} ended with status {status}."
            )

        time.sleep(min(poll_interval, max(0.0, deadline - time.monotonic())))


__all__ = [
    "submit_job",
    "poll_status",
    "poll_until_done",
    "cancel_job",
]
