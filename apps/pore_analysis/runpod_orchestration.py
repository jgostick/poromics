from __future__ import annotations


class RunPodOrchestrationHook:
    """No-op seam for future worker-driven RunPod pod lifecycle orchestration.

    The current implementation is intentionally passive so queue routing behavior
    remains unchanged while exposing a stable call path for future autoscaling.
    """

    def ensure_pod_exists(self, *, queue_name: str, analysis_type: str, endpoint_url: str) -> None:
        _ = (queue_name, analysis_type, endpoint_url)

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
