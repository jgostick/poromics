"""RunPod ephemeral pod lifecycle for analysis workers.

Each job that uses the taichi-runpod-pod queue creates a fresh RunPod pod, waits for it to
reach RUNNING, runs the analysis, and terminates the pod immediately afterwards (in a
finally block). This avoids the reliability problems associated with resuming paused pods.

The taichi-runpod-serverless queue does not use this module — RunPod Serverless manages
its own worker lifecycle.
"""
from __future__ import annotations

import logging
import time

from django.conf import settings

from apps.utils.runpod_pods import (
    RunPodConfigurationError,
    RunPodNotFoundError,
    RunPodTransientError,
    create_pod,
    list_pods,
    terminate_pod,
)

log = logging.getLogger(__name__)

# Naming prefix used to identify pods created by this module.
# The cleanup task uses this to find orphaned pods.
EPHEMERAL_POD_NAME_PREFIX = "taichi-ephemeral-"


def _pod_spec_for_queue(queue_name: str) -> dict:
    """Return the pod creation spec for *queue_name* from settings.

    Raises RunPodConfigurationError if no spec is configured.
    """
    specs: dict[str, dict] = getattr(settings, "RUNPOD_POD_QUEUE_SPECS", {})
    spec = specs.get(queue_name)
    if not spec:
        raise RunPodConfigurationError(
            f"No pod spec configured for queue '{queue_name}'. "
            "Set RUNPOD_POD_QUEUE_SPECS in settings with a JSON mapping of "
            "queue_name → RunPod pod creation spec."
        )
    return dict(spec)


def _startup_timeout() -> float:
    return max(0.0, float(getattr(settings, "RUNPOD_POD_STARTUP_TIMEOUT_SECONDS", 300.0)))


def _startup_poll_interval() -> float:
    return max(0.5, float(getattr(settings, "RUNPOD_POD_STARTUP_POLL_INTERVAL_SECONDS", 5.0)))


def _taichi_port() -> int:
    return int(getattr(settings, "RUNPOD_POD_TAICHI_PORT", 3000))


def _status_value(value: str | None) -> str:
    return str(value or "").strip().upper()


def _find_pod_by_id(pod_id: str) -> dict | None:
    for pod in list_pods():
        if str(pod.get("id") or "").strip() == pod_id:
            return pod
    return None


def create_ephemeral_pod(queue_name: str) -> tuple[str, str]:
    """Create a fresh RunPod pod for *queue_name*, wait until it is RUNNING, and return
    ``(pod_id, endpoint_url)`` where ``endpoint_url`` is the RunPod HTTP proxy URL for
    the taichi server port:  ``https://{pod_id}-{port}.proxy.runpod.net``.

    Raises:
        RunPodConfigurationError: if no pod spec is configured for *queue_name*.
        RunPodTransientError: if the pod does not reach RUNNING within the timeout.
    """
    spec = _pod_spec_for_queue(queue_name)
    # Force a predictable name prefix so the cleanup task can identify orphaned pods.
    spec.setdefault("name", EPHEMERAL_POD_NAME_PREFIX + queue_name)

    log.info("Creating ephemeral RunPod pod for queue '%s' (spec name=%s)", queue_name, spec.get("name"))
    pod = create_pod(spec)
    pod_id = str(pod.get("id") or "").strip()
    if not pod_id:
        raise RunPodTransientError("RunPod pod creation response did not include a pod id.")

    log.info("Pod %s created for queue '%s'; waiting for RUNNING state", pod_id, queue_name)

    timeout = _startup_timeout()
    poll_interval = _startup_poll_interval()
    started_at = time.monotonic()
    deadline = started_at + timeout

    while True:
        pod_info = _find_pod_by_id(pod_id)
        if pod_info:
            status = _status_value(pod_info.get("status"))
            desired_status = _status_value(pod_info.get("desired_status"))
            if status == "RUNNING" or desired_status == "RUNNING":
                elapsed = time.monotonic() - started_at
                port = _taichi_port()
                endpoint_url = f"https://{pod_id}-{port}.proxy.runpod.net"
                log.info(
                    "Pod %s is RUNNING for queue '%s' after %.1fs; endpoint=%s",
                    pod_id,
                    queue_name,
                    elapsed,
                    endpoint_url,
                )
                return pod_id, endpoint_url

        now = time.monotonic()
        if now >= deadline:
            raise RunPodTransientError(
                f"Timed out waiting for pod {pod_id} (queue '{queue_name}') to reach RUNNING "
                f"after {timeout:.0f}s."
            )

        time.sleep(min(poll_interval, max(0.0, deadline - now)))


def terminate_ephemeral_pod(pod_id: str) -> None:
    """Terminate a pod created by :func:`create_ephemeral_pod`.

    Swallows ``RunPodNotFoundError`` (pod already gone) and logs but does not re-raise
    any other error, so this is always safe to call from a ``finally`` block.
    """
    try:
        terminate_pod(pod_id)
        log.info("Ephemeral pod %s terminated", pod_id)
    except RunPodNotFoundError:
        log.info("Ephemeral pod %s was already gone when termination was requested", pod_id)
    except Exception:
        log.exception(
            "Failed to terminate ephemeral pod %s — it may need to be cleaned up manually",
            pod_id,
        )


def terminate_orphaned_ephemeral_pods(max_age_seconds: float | None = None) -> int:
    """Find and terminate pods whose name starts with :data:`EPHEMERAL_POD_NAME_PREFIX`
    and that have been running longer than *max_age_seconds*.

    Returns the number of pods terminated.  Called by the Celery Beat cleanup task.
    """
    if max_age_seconds is None:
        max_age_seconds = float(getattr(settings, "RUNPOD_POD_MAX_AGE_SECONDS", 3600.0))

    terminated = 0
    try:
        pods = list_pods()
    except Exception:
        log.exception("Failed to list RunPod pods during orphan cleanup")
        return 0

    import time as _time

    now_ts = _time.time()

    for pod in pods:
        name = str(pod.get("name") or "")
        if not name.startswith(EPHEMERAL_POD_NAME_PREFIX):
            continue

        # RunPod returns runtime.uptimeInSeconds or similar; fall back to uptime if available.
        runtime = pod.get("runtime") or {}
        uptime = runtime.get("uptimeInSeconds")
        if uptime is None:
            # If we cannot determine age, skip to avoid false positives.
            log.debug("Skipping pod %s — cannot determine uptime", pod.get("id"))
            continue

        if float(uptime) < max_age_seconds:
            continue

        pod_id = str(pod.get("id") or "").strip()
        if not pod_id:
            continue

        log.warning(
            "Terminating orphaned ephemeral pod %s (name=%s, uptime=%.0fs)",
            pod_id,
            name,
            float(uptime),
        )
        terminate_ephemeral_pod(pod_id)
        terminated += 1

    return terminated


__all__ = [
    "EPHEMERAL_POD_NAME_PREFIX",
    "create_ephemeral_pod",
    "terminate_ephemeral_pod",
    "terminate_orphaned_ephemeral_pods",
]
