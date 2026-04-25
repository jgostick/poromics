from __future__ import annotations

import logging
import time

from django.conf import settings

from apps.utils.runpod_pods import RunPodTransientError, list_pods, resume_pod

log = logging.getLogger(__name__)


def _status_value(value: str | None) -> str:
    return str(value or "").strip().upper()


def _wake_enabled() -> bool:
    return bool(getattr(settings, "RUNPOD_WORKER_WAKE_ENABLED", False))


def _queue_pod_ids() -> dict[str, str]:
    raw = getattr(settings, "RUNPOD_QUEUE_POD_IDS", {})
    if not isinstance(raw, dict):
        return {}

    mapping: dict[str, str] = {}
    for queue_name, pod_id in raw.items():
        normalized_queue = str(queue_name).strip()
        normalized_pod = str(pod_id).strip()
        if normalized_queue and normalized_pod:
            mapping[normalized_queue] = normalized_pod
    return mapping


def _wake_timeout_seconds() -> float:
    return max(0.0, float(getattr(settings, "RUNPOD_WAKE_TIMEOUT_SECONDS", 300.0)))


def _wake_poll_interval_seconds() -> float:
    return max(0.1, float(getattr(settings, "RUNPOD_WAKE_POLL_INTERVAL_SECONDS", 5.0)))


def _find_pod(pod_id: str) -> dict[str, str] | None:
    for pod in list_pods():
        if str(pod.get("id") or "").strip() == pod_id:
            return pod
    return None


class RunPodOrchestrationHook:
    """No-op seam for future worker-driven RunPod pod lifecycle orchestration.

    The current implementation is intentionally passive so queue routing behavior
    remains unchanged while exposing a stable call path for future autoscaling.
    """

    def ensure_pod_exists(self, *, queue_name: str, analysis_type: str, endpoint_url: str) -> None:
        _ = analysis_type

        if not _wake_enabled():
            return

        if not str(endpoint_url or "").strip():
            return

        pod_id = _queue_pod_ids().get(queue_name)
        if not pod_id:
            return

        timeout_seconds = _wake_timeout_seconds()
        poll_interval = _wake_poll_interval_seconds()
        started_at = time.monotonic()
        deadline = started_at + timeout_seconds
        resume_attempted = False
        last_status = "unknown"
        last_desired_status = ""

        while True:
            pod = _find_pod(pod_id)
            if pod:
                status = _status_value(pod.get("status"))
                desired_status = _status_value(pod.get("desired_status"))
                last_status = status or "unknown"
                last_desired_status = desired_status

                if status == "RUNNING" or desired_status == "RUNNING":
                    elapsed_seconds = time.monotonic() - started_at
                    log.info(
                        "RunPod pod %s ready for queue '%s' after %.2fs (status=%s, desired_status=%s)",
                        pod_id,
                        queue_name,
                        elapsed_seconds,
                        status,
                        desired_status or "n/a",
                    )
                    return
            else:
                last_status = "missing"
                last_desired_status = ""

            if not resume_attempted:
                log.info(
                    "RunPod pod %s for queue '%s' is not running (status=%s, desired_status=%s); requesting start",
                    pod_id,
                    queue_name,
                    last_status,
                    last_desired_status or "n/a",
                )
                resume_pod(pod_id)
                resume_attempted = True

            now = time.monotonic()
            if now >= deadline:
                raise RunPodTransientError(
                    "Timed out waiting for RunPod pod "
                    f"{pod_id} to reach RUNNING for queue '{queue_name}' "
                    f"(last_status={last_status}, desired_status={last_desired_status or 'n/a'})."
                )

            time.sleep(min(poll_interval, max(0.0, deadline - now)))

    def pause_idle_pod(self, *, queue_name: str, reason: str | None = None) -> None:
        _ = (queue_name, reason)

    def terminate_broken_pod(self, *, queue_name: str, reason: str | None = None) -> None:
        _ = (queue_name, reason)


def get_runpod_orchestration_hook() -> RunPodOrchestrationHook:
    return RunPodOrchestrationHook()


def maybe_ensure_runpod_pod(*, queue_name: str, analysis_type: str, endpoint_url: str) -> None:
    hook = get_runpod_orchestration_hook()
    hook.ensure_pod_exists(queue_name=queue_name, analysis_type=analysis_type, endpoint_url=endpoint_url)


def maybe_pause_runpod_pod(*, queue_name: str, reason: str | None = None) -> None:
    hook = get_runpod_orchestration_hook()
    hook.pause_idle_pod(queue_name=queue_name, reason=reason)


def maybe_terminate_runpod_pod(*, queue_name: str, reason: str | None = None) -> None:
    hook = get_runpod_orchestration_hook()
    hook.terminate_broken_pod(queue_name=queue_name, reason=reason)


__all__ = [
    "RunPodOrchestrationHook",
    "get_runpod_orchestration_hook",
    "maybe_ensure_runpod_pod",
    "maybe_pause_runpod_pod",
    "maybe_terminate_runpod_pod",
]
