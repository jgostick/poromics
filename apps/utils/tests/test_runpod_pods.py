from __future__ import annotations

from unittest.mock import patch

import httpx
from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from apps.utils import runpod_pods

LOC_MEM_CACHE = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "runpod-tests",
    }
}


def _response(method: str, url: str, status_code: int, payload):
    return httpx.Response(status_code=status_code, json=payload, request=httpx.Request(method, url))


@override_settings(
    CACHES=LOC_MEM_CACHE,
    RUNPOD_API_BASE_URL="https://rest.runpod.io/v1",
    RUNPOD_API_KEY="test-key",
    RUNPOD_DEFAULT_PORTS=["8888/http", "22/tcp"],
)
class RunPodPodServiceTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_list_pods_normalizes_expected_fields(self):
        payload = {
            "pods": [
                {
                    "id": "pod-1",
                    "name": "alpha",
                    "status": "RUNNING",
                    "imageName": "ghcr.io/example/image:latest",
                    "gpuTypeId": "NVIDIA_A5000",
                    "endpointUrl": "https://runpod-alpha.example",
                }
            ]
        }

        with patch("apps.utils.runpod_pods._request_json", return_value=payload):
            pods = runpod_pods.list_pods()

        self.assertEqual(len(pods), 1)
        self.assertEqual(pods[0]["id"], "pod-1")
        self.assertEqual(pods[0]["name"], "alpha")
        self.assertEqual(pods[0]["image_name"], "ghcr.io/example/image:latest")
        self.assertEqual(pods[0]["gpu_type_id"], "NVIDIA_A5000")
        self.assertEqual(pods[0]["endpoint_url"], "https://runpod-alpha.example")

    def test_get_creation_options_parses_openapi_enums(self):
        openapi = {
            "components": {
                "schemas": {
                    "PodCreateInput": {
                        "type": "object",
                        "properties": {
                            "gpuTypeIds": {"type": "string", "enum": ["NVIDIA_A5000", "NVIDIA_A6000"]},
                            "cpuFlavorIds": {"type": "string", "enum": ["16vCPU_32GB"]},
                            "dataCenterIds": {"type": "string", "enum": ["US-CA-1"]},
                            "allowedCudaVersions": {"type": "string", "enum": ["12.4"]},
                            "cloudType": {"type": "string", "enum": ["SECURE", "COMMUNITY"]},
                            "computeType": {"type": "string", "enum": ["GPU", "CPU"]},
                            "ports": {"type": "array", "items": {"type": "string"}},
                            "env": {"type": "object"},
                        },
                    }
                }
            }
        }

        with patch("apps.utils.runpod_pods._request_json", return_value=openapi):
            options = runpod_pods.get_creation_options(force_refresh=True)

        self.assertEqual(options["source"], "openapi")
        self.assertIn("NVIDIA_A5000", options["gpu_type_ids"])
        self.assertIn("16vCPU_32GB", options["cpu_flavor_ids"])
        self.assertIn("US-CA-1", options["data_center_ids"])
        self.assertIn("12.4", options["allowed_cuda_versions"])

    def test_get_creation_options_falls_back_to_stale_cache(self):
        stale = runpod_pods.default_creation_options()
        stale["source"] = "openapi"
        cache.set(runpod_pods._OPENAPI_STALE_CACHE_KEY, stale, timeout=60)

        with patch(
            "apps.utils.runpod_pods._request_json",
            side_effect=runpod_pods.RunPodTransientError("temporary error", retryable=True),
        ):
            options = runpod_pods.get_creation_options(force_refresh=True)

        self.assertEqual(options["source"], "stale-cache")
        self.assertIn("warning", options)

    def test_create_pod_uses_existing_name_for_idempotency(self):
        existing = {
            "id": "pod-existing",
            "name": "runner-a",
            "status": "RUNNING",
            "image_name": "ghcr.io/example/runner:latest",
        }

        with patch("apps.utils.runpod_pods.list_pods", return_value=[existing]):
            created = runpod_pods.create_pod(
                {
                    "pod_name": "runner-a",
                    "image_name": "ghcr.io/example/runner:latest",
                    "compute_type": "GPU",
                    "gpu_type_id": "NVIDIA_A5000",
                }
            )

        self.assertEqual(created["id"], "pod-existing")
        self.assertTrue(created["idempotent"])

    def test_create_pod_without_image_omits_image_field(self):
        created_payload = {"id": "pod-1", "name": "runner-a", "status": "RUNNING"}
        options = runpod_pods.default_creation_options()

        with (
            patch("apps.utils.runpod_pods.list_pods", return_value=[]),
            patch("apps.utils.runpod_pods.get_creation_options", return_value=options),
            patch("apps.utils.runpod_pods._request_json", return_value=created_payload) as request_mock,
        ):
            created = runpod_pods.create_pod(
                {
                    "pod_name": "runner-a",
                    "image_name": "",
                    "compute_type": "GPU",
                    "gpu_type_id": "NVIDIA_A5000",
                }
            )

        self.assertEqual(created["id"], "pod-1")
        _, kwargs = request_mock.call_args
        body = kwargs.get("body") or {}
        image_field = options["schema_fields"]["image_name"]
        self.assertNotIn(image_field, body)

    def test_create_pod_wraps_cpu_flavor_when_schema_requires_array(self):
        created_payload = {"id": "pod-cpu-1", "name": "runner-cpu", "status": "RUNNING"}
        options = runpod_pods.default_creation_options()
        options["schema_fields"]["cpu_flavor_id"] = "cpuFlavorIds"
        options["schema_field_types"]["cpu_flavor_id"] = "array"

        with (
            patch("apps.utils.runpod_pods.list_pods", return_value=[]),
            patch("apps.utils.runpod_pods.get_creation_options", return_value=options),
            patch("apps.utils.runpod_pods._request_json", return_value=created_payload) as request_mock,
        ):
            created = runpod_pods.create_pod(
                {
                    "pod_name": "runner-cpu",
                    "compute_type": "CPU",
                    "cpu_flavor_id": "16vCPU_32GB",
                }
            )

        self.assertEqual(created["id"], "pod-cpu-1")
        _, kwargs = request_mock.call_args
        body = kwargs.get("body") or {}
        self.assertEqual(body.get("cpuFlavorIds"), ["16vCPU_32GB"])

    def test_create_pod_infers_array_from_legacy_schema_field_name(self):
        created_payload = {"id": "pod-cpu-2", "name": "runner-cpu-legacy", "status": "RUNNING"}
        options = runpod_pods.default_creation_options()
        options["schema_fields"]["cpu_flavor_id"] = "cpuFlavorIds"
        options["schema_field_types"].pop("cpu_flavor_id", None)

        with (
            patch("apps.utils.runpod_pods.list_pods", return_value=[]),
            patch("apps.utils.runpod_pods.get_creation_options", return_value=options),
            patch("apps.utils.runpod_pods._request_json", return_value=created_payload) as request_mock,
        ):
            created = runpod_pods.create_pod(
                {
                    "pod_name": "runner-cpu-legacy",
                    "compute_type": "CPU",
                    "cpu_flavor_id": "16vCPU_32GB",
                }
            )

        self.assertEqual(created["id"], "pod-cpu-2")
        _, kwargs = request_mock.call_args
        body = kwargs.get("body") or {}
        self.assertEqual(body.get("cpuFlavorIds"), ["16vCPU_32GB"])

    def test_terminate_pod_is_idempotent_for_not_found(self):
        with patch(
            "apps.utils.runpod_pods._request_json",
            side_effect=runpod_pods.RunPodNotFoundError("missing"),
        ):
            result = runpod_pods.terminate_pod("pod-missing")

        self.assertEqual(result["id"], "pod-missing")
        self.assertFalse(result["terminated"])
        self.assertTrue(result["idempotent"])

    def test_request_json_retries_on_timeout(self):
        url = "https://rest.runpod.io/v1/pods"
        timeout_error = httpx.TimeoutException("timeout")
        ok_response = _response("GET", url, 200, {"pods": []})

        with (
            patch("apps.utils.runpod_pods.time.sleep", return_value=None),
            patch("apps.utils.runpod_pods.httpx.Client.request", side_effect=[timeout_error, ok_response]) as req,
        ):
            payload = runpod_pods._request_json("GET", "/pods", expected_statuses={200})

        self.assertEqual(payload, {"pods": []})
        self.assertEqual(req.call_count, 2)

    @override_settings(
        RUNPOD_REGISTRY_AUTH_ID="",
        RUNPOD_REGISTRY_USERNAME="demo-user",
        RUNPOD_REGISTRY_PAT="demo-token",
    )
    def test_resolve_registry_auth_id_creates_with_required_name_field(self):
        with patch(
            "apps.utils.runpod_pods._request_json",
            side_effect=[{"items": []}, {"id": "reg-1"}],
        ) as request_mock:
            registry_auth_id = runpod_pods._resolve_registry_auth_id()

        self.assertEqual(registry_auth_id, "reg-1")
        self.assertEqual(request_mock.call_count, 2)

        _, second_call_kwargs = request_mock.call_args_list[1]
        body = second_call_kwargs.get("body") or {}
        self.assertEqual(body.get("name"), "ghcr-demo-user")
        self.assertEqual(body.get("username"), "demo-user")
        self.assertEqual(body.get("registry"), "ghcr.io")

    @override_settings(
        RUNPOD_REGISTRY_AUTH_ID="",
        RUNPOD_REGISTRY_AUTH_NAME="custom-ghcr-auth",
        RUNPOD_REGISTRY_USERNAME="demo-user",
        RUNPOD_REGISTRY_PAT="demo-token",
    )
    def test_resolve_registry_auth_id_uses_configured_registry_auth_name(self):
        with patch(
            "apps.utils.runpod_pods._request_json",
            side_effect=[{"items": []}, {"id": "reg-2"}],
        ) as request_mock:
            registry_auth_id = runpod_pods._resolve_registry_auth_id()

        self.assertEqual(registry_auth_id, "reg-2")
        _, second_call_kwargs = request_mock.call_args_list[1]
        body = second_call_kwargs.get("body") or {}
        self.assertEqual(body.get("name"), "custom-ghcr-auth")

    @override_settings(
        RUNPOD_REGISTRY_AUTH_ID="",
        RUNPOD_REGISTRY_AUTH_NAME="custom-ghcr-auth",
        RUNPOD_REGISTRY_USERNAME="demo-user",
        RUNPOD_REGISTRY_PAT="demo-token",
    )
    def test_resolve_registry_auth_id_retries_with_slimmer_payload_on_extra_keys_error(self):
        with patch(
            "apps.utils.runpod_pods._request_json",
            side_effect=[
                {"items": []},
                runpod_pods.RunPodValidationError("Extra input keys provided in request body"),
                {"id": "reg-3"},
            ],
        ) as request_mock:
            registry_auth_id = runpod_pods._resolve_registry_auth_id()

        self.assertEqual(registry_auth_id, "reg-3")
        self.assertEqual(request_mock.call_count, 3)

        _, first_post_kwargs = request_mock.call_args_list[1]
        _, second_post_kwargs = request_mock.call_args_list[2]

        first_payload = first_post_kwargs.get("body") or {}
        second_payload = second_post_kwargs.get("body") or {}

        self.assertIn("isDefault", first_payload)
        self.assertNotIn("isDefault", second_payload)
        self.assertEqual(second_payload.get("name"), "custom-ghcr-auth")
