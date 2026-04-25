from __future__ import annotations

from unittest.mock import patch

from django.test import Client, TestCase
from django.urls import reverse

from apps.users.models import CustomUser


class AdminPodsViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.superuser = CustomUser.objects.create_superuser(
            username="admin@example.com",
            email="admin@example.com",
            password="12345",
        )
        cls.regular_user = CustomUser.objects.create_user(
            username="user@example.com",
            email="user@example.com",
            password="12345",
        )

    def setUp(self):
        self.client = Client()

    def test_admin_pods_requires_superuser(self):
        self.client.login(username="user@example.com", password="12345")
        url = reverse("dashboard:admin_pods")

        response = self.client.get(url)

        self.assertRedirects(response, f"/404?next={url}", fetch_redirect_response=False)

    def test_admin_pods_superuser_get_renders(self):
        self.client.login(username="admin@example.com", password="12345")

        with (
            patch("apps.dashboard.views.runpod_pods.get_creation_options", return_value={"compute_types": ["GPU"]}),
            patch(
                "apps.dashboard.views.runpod_pods.list_pods",
                return_value=[{"id": "pod-1", "name": "runner-a", "status": "RUNNING"}],
            ),
        ):
            response = self.client.get(reverse("dashboard:admin_pods"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "runner-a")

    def test_admin_pods_post_creates_pod_via_shared_service(self):
        self.client.login(username="admin@example.com", password="12345")
        options = {
            "compute_types": ["GPU", "CPU"],
            "cloud_types": ["SECURE", "COMMUNITY"],
            "gpu_type_ids": ["NVIDIA_A5000"],
            "cpu_flavor_ids": ["16vCPU_32GB"],
            "data_center_ids": ["US-CA-1"],
            "default_compute_type": "GPU",
            "default_cloud_type": "SECURE",
            "source": "openapi",
        }
        payload = {
            "pod_name": "runner-a",
            "image_name": "ghcr.io/example/runner:latest",
            "compute_type": "GPU",
            "gpu_type_id": "NVIDIA_A5000",
            "cpu_flavor_id": "",
            "data_center_id": "US-CA-1",
            "cloud_type": "SECURE",
            "interruptible": "on",
            "ports": "8888/http\n22/tcp",
            "env_vars": "HELLO=WORLD",
        }

        with (
            patch("apps.dashboard.views.runpod_pods.get_creation_options", return_value=options),
            patch(
                "apps.dashboard.views.runpod_pods.create_pod", return_value={"id": "pod-1", "name": "runner-a"}
            ) as create_mock,
        ):
            response = self.client.post(reverse("dashboard:admin_pods"), payload)

        self.assertRedirects(response, reverse("dashboard:admin_pods"), fetch_redirect_response=False)
        create_mock.assert_called_once()

    def test_admin_pods_post_allows_blank_image_name(self):
        self.client.login(username="admin@example.com", password="12345")
        options = {
            "compute_types": ["GPU", "CPU"],
            "cloud_types": ["SECURE", "COMMUNITY"],
            "gpu_type_ids": ["NVIDIA_A5000"],
            "cpu_flavor_ids": ["16vCPU_32GB"],
            "data_center_ids": ["US-CA-1"],
            "default_compute_type": "GPU",
            "default_cloud_type": "SECURE",
            "source": "openapi",
        }
        payload = {
            "pod_name": "runner-a",
            "image_name": "",
            "compute_type": "GPU",
            "gpu_type_id": "NVIDIA_A5000",
            "cpu_flavor_id": "",
            "data_center_id": "US-CA-1",
            "cloud_type": "SECURE",
            "ports": "8888/http\n22/tcp",
            "env_vars": "HELLO=WORLD",
        }

        with (
            patch("apps.dashboard.views.runpod_pods.get_creation_options", return_value=options),
            patch(
                "apps.dashboard.views.runpod_pods.create_pod", return_value={"id": "pod-1", "name": "runner-a"}
            ) as create_mock,
        ):
            response = self.client.post(reverse("dashboard:admin_pods"), payload)

        self.assertRedirects(response, reverse("dashboard:admin_pods"), fetch_redirect_response=False)
        create_mock.assert_called_once()
        submitted_spec = create_mock.call_args.args[0]
        self.assertEqual(submitted_spec["image_name"], "")

    def test_admin_pod_action_dispatches_to_service_methods(self):
        self.client.login(username="admin@example.com", password="12345")
        action_map = {
            "pause": "pause_pod",
            "resume": "resume_pod",
            "terminate": "terminate_pod",
        }

        for action, service_name in action_map.items():
            with self.subTest(action=action):
                target = f"apps.dashboard.views.runpod_pods.{service_name}"
                with patch(target, return_value={"id": "pod-1", "terminated": True}) as action_mock:
                    response = self.client.post(
                        reverse("dashboard:admin_pod_action", kwargs={"pod_id": "pod-1"}),
                        {"action": action},
                    )

                self.assertRedirects(response, reverse("dashboard:admin_pods"), fetch_redirect_response=False)
                action_mock.assert_called_once_with("pod-1")
