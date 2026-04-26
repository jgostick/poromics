from django.test import TestCase, override_settings

from apps.pore_analysis.models import RunPodQueueMapping
from apps.pore_analysis.queue_catalog import (
    get_queue_endpoint,
    get_runpod_queue_choices,
    get_runtime_runpod_queue_pod_ids,
)


class QueueCatalogRuntimeMappingTests(TestCase):
    @override_settings(TAICHI_QUEUE_ENDPOINTS={"taichi-runpod": "https://settings.example"})
    def test_runtime_endpoint_mapping_takes_precedence(self):
        RunPodQueueMapping.objects.create(
            queue_name="taichi-runpod",
            pod_id="pod-1",
            pod_name="taichi-a",
            endpoint_url="https://runtime.example",
        )

        endpoint = get_queue_endpoint("taichi-runpod", default="")

        self.assertEqual(endpoint, "https://runtime.example")

    @override_settings(TAICHI_QUEUE_ENDPOINTS={"taichi-runpod": "https://settings.example"})
    def test_queue_endpoint_falls_back_to_settings_when_runtime_mapping_missing(self):
        endpoint = get_queue_endpoint("taichi-runpod", default="")

        self.assertEqual(endpoint, "https://settings.example")

    def test_runtime_queue_pod_id_map_reads_database_rows(self):
        RunPodQueueMapping.objects.create(
            queue_name="taichi-runpod",
            pod_id="pod-taichi",
            pod_name="taichi-a",
            endpoint_url="https://taichi.example",
        )
        RunPodQueueMapping.objects.create(
            queue_name="poresize-runpod",
            pod_id="pod-cpu",
            pod_name="cpu-a",
            endpoint_url="https://cpu.example",
        )

        mapping = get_runtime_runpod_queue_pod_ids()

        self.assertEqual(mapping["taichi-runpod"], "pod-taichi")
        self.assertEqual(mapping["poresize-runpod"], "pod-cpu")

    def test_runpod_queue_choices_include_only_runpod_named_queues(self):
        choice_names = {queue_name for queue_name, _ in get_runpod_queue_choices()}

        self.assertIn("taichi-runpod", choice_names)
        self.assertIn("poresize-runpod", choice_names)
        self.assertIn("extraction-runpod", choice_names)
        self.assertNotIn("kabs-cpu", choice_names)
