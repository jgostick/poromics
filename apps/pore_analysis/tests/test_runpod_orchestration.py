from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from apps.pore_analysis.runpod_orchestration import RunPodOrchestrationHook
from apps.utils.runpod_pods import RunPodNotFoundError, RunPodTransientError


class RunPodOrchestrationHookTests(SimpleTestCase):
    @override_settings(
        RUNPOD_WORKER_WAKE_ENABLED=False,
        RUNPOD_QUEUE_POD_IDS={"taichi-runpod": "pod-1"},
    )
    def test_does_nothing_when_worker_wake_is_disabled(self):
        hook = RunPodOrchestrationHook()

        with (
            patch("apps.pore_analysis.runpod_orchestration.list_pods") as list_mock,
            patch("apps.pore_analysis.runpod_orchestration.resume_pod") as resume_mock,
        ):
            hook.ensure_pod_exists(
                queue_name="taichi-runpod",
                analysis_type="permeability",
                endpoint_url="https://example.runpod.dev",
            )

        list_mock.assert_not_called()
        resume_mock.assert_not_called()

    @override_settings(
        RUNPOD_WORKER_WAKE_ENABLED=True,
        RUNPOD_QUEUE_POD_IDS={},
    )
    def test_does_nothing_when_queue_has_no_pod_mapping(self):
        hook = RunPodOrchestrationHook()

        with (
            patch("apps.pore_analysis.runpod_orchestration.list_pods") as list_mock,
            patch("apps.pore_analysis.runpod_orchestration.resume_pod") as resume_mock,
        ):
            hook.ensure_pod_exists(
                queue_name="taichi-runpod",
                analysis_type="permeability",
                endpoint_url="https://example.runpod.dev",
            )

        list_mock.assert_not_called()
        resume_mock.assert_not_called()

    @override_settings(
        RUNPOD_WORKER_WAKE_ENABLED=True,
        RUNPOD_QUEUE_POD_IDS={"taichi-runpod": "pod-1"},
    )
    def test_does_nothing_when_endpoint_is_blank(self):
        hook = RunPodOrchestrationHook()

        with (
            patch("apps.pore_analysis.runpod_orchestration.list_pods") as list_mock,
            patch("apps.pore_analysis.runpod_orchestration.resume_pod") as resume_mock,
        ):
            hook.ensure_pod_exists(
                queue_name="taichi-runpod",
                analysis_type="permeability",
                endpoint_url="",
            )

        list_mock.assert_not_called()
        resume_mock.assert_not_called()

    @override_settings(
        RUNPOD_WORKER_WAKE_ENABLED=True,
        RUNPOD_QUEUE_POD_IDS={"taichi-runpod": "pod-1"},
    )
    def test_returns_immediately_when_pod_is_already_running(self):
        hook = RunPodOrchestrationHook()

        with (
            patch(
                "apps.pore_analysis.runpod_orchestration.list_pods",
                return_value=[{"id": "pod-1", "status": "RUNNING"}],
            ) as list_mock,
            patch("apps.pore_analysis.runpod_orchestration.resume_pod") as resume_mock,
        ):
            hook.ensure_pod_exists(
                queue_name="taichi-runpod",
                analysis_type="permeability",
                endpoint_url="https://example.runpod.dev",
            )

        self.assertEqual(list_mock.call_count, 1)
        resume_mock.assert_not_called()

    @override_settings(
        RUNPOD_WORKER_WAKE_ENABLED=True,
        RUNPOD_QUEUE_POD_IDS={"taichi-runpod": "pod-settings"},
    )
    def test_runtime_mapping_takes_precedence_over_settings_mapping(self):
        hook = RunPodOrchestrationHook()

        with (
            patch(
                "apps.pore_analysis.runpod_orchestration.get_runtime_runpod_queue_pod_ids",
                return_value={"taichi-runpod": "pod-runtime"},
            ),
            patch(
                "apps.pore_analysis.runpod_orchestration.list_pods",
                return_value=[{"id": "pod-runtime", "status": "RUNNING"}],
            ) as list_mock,
            patch("apps.pore_analysis.runpod_orchestration.resume_pod") as resume_mock,
        ):
            hook.ensure_pod_exists(
                queue_name="taichi-runpod",
                analysis_type="permeability",
                endpoint_url="https://example.runpod.dev",
            )

        self.assertEqual(list_mock.call_count, 1)
        resume_mock.assert_not_called()

    @override_settings(
        RUNPOD_WORKER_WAKE_ENABLED=True,
        RUNPOD_QUEUE_POD_IDS={},
    )
    def test_runtime_mapping_without_settings_mapping_is_used(self):
        hook = RunPodOrchestrationHook()

        with (
            patch(
                "apps.pore_analysis.runpod_orchestration.get_runtime_runpod_queue_pod_ids",
                return_value={"taichi-runpod": "pod-runtime"},
            ),
            patch(
                "apps.pore_analysis.runpod_orchestration.list_pods",
                return_value=[{"id": "pod-runtime", "status": "RUNNING"}],
            ) as list_mock,
            patch("apps.pore_analysis.runpod_orchestration.resume_pod") as resume_mock,
        ):
            hook.ensure_pod_exists(
                queue_name="taichi-runpod",
                analysis_type="permeability",
                endpoint_url="https://example.runpod.dev",
            )

        self.assertEqual(list_mock.call_count, 1)
        resume_mock.assert_not_called()

    @override_settings(
        RUNPOD_WORKER_WAKE_ENABLED=True,
        RUNPOD_QUEUE_POD_IDS={"taichi-runpod": "pod-1"},
        RUNPOD_WAKE_TIMEOUT_SECONDS=5.0,
        RUNPOD_WAKE_POLL_INTERVAL_SECONDS=0.1,
    )
    def test_resumes_pod_and_waits_until_running(self):
        hook = RunPodOrchestrationHook()
        pod_states = [
            [{"id": "pod-1", "status": "PAUSED"}],
            [{"id": "pod-1", "status": "RUNNING"}],
        ]

        with (
            patch("apps.pore_analysis.runpod_orchestration.list_pods", side_effect=pod_states) as list_mock,
            patch("apps.pore_analysis.runpod_orchestration.resume_pod", return_value={"id": "pod-1"}) as resume_mock,
            patch("apps.pore_analysis.runpod_orchestration.time.sleep", return_value=None) as sleep_mock,
        ):
            hook.ensure_pod_exists(
                queue_name="taichi-runpod",
                analysis_type="permeability",
                endpoint_url="https://example.runpod.dev",
            )

        self.assertEqual(list_mock.call_count, 2)
        resume_mock.assert_called_once_with("pod-1")
        sleep_mock.assert_called_once()

    @override_settings(
        RUNPOD_WORKER_WAKE_ENABLED=True,
        RUNPOD_QUEUE_POD_IDS={"taichi-runpod": "pod-1"},
        RUNPOD_WAKE_TIMEOUT_SECONDS=0.0,
        RUNPOD_WAKE_POLL_INTERVAL_SECONDS=0.1,
    )
    def test_raises_timeout_when_pod_never_reaches_running(self):
        hook = RunPodOrchestrationHook()

        with (
            patch(
                "apps.pore_analysis.runpod_orchestration.list_pods",
                return_value=[{"id": "pod-1", "status": "PAUSED"}],
            ),
            patch("apps.pore_analysis.runpod_orchestration.resume_pod", return_value={"id": "pod-1"}) as resume_mock,
            self.assertRaises(RunPodTransientError),
        ):
            hook.ensure_pod_exists(
                queue_name="taichi-runpod",
                analysis_type="permeability",
                endpoint_url="https://example.runpod.dev",
            )

        resume_mock.assert_called_once_with("pod-1")

    @override_settings(
        RUNPOD_WORKER_WAKE_ENABLED=True,
        RUNPOD_QUEUE_POD_IDS={"taichi-runpod": "pod-1"},
        RUNPOD_WAKE_TIMEOUT_SECONDS=1.0,
    )
    def test_propagates_not_found_error_from_resume(self):
        hook = RunPodOrchestrationHook()

        with (
            patch("apps.pore_analysis.runpod_orchestration.list_pods", return_value=[]),
            patch(
                "apps.pore_analysis.runpod_orchestration.resume_pod",
                side_effect=RunPodNotFoundError("missing pod"),
            ) as resume_mock,
            self.assertRaises(RunPodNotFoundError),
        ):
            hook.ensure_pod_exists(
                queue_name="taichi-runpod",
                analysis_type="permeability",
                endpoint_url="https://example.runpod.dev",
            )

        resume_mock.assert_called_once_with("pod-1")