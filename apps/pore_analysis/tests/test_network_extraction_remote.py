import numpy as np
from django.test import SimpleTestCase
from unittest.mock import patch

from apps.pore_analysis.analysis.network_extraction import run_network_extraction


class NetworkExtractionRemoteTests(SimpleTestCase):
    @patch("apps.pore_analysis.analysis.network_extraction.time.sleep", return_value=None)
    def test_run_network_extraction_remote_path_returns_remote_output(self, _sleep):
        image_array = np.ones((2, 2, 2), dtype=bool)
        remote_output = {
            "method": "snow2",
            "net": {
                "pore.coords": [[0.0, 0.0, 0.0]],
                "throat.conns": [[0, 0]],
            },
        }

        with (
            patch("python_remote_client.submit_job", return_value="job-456") as submit_mock,
            patch("python_remote_client.poll_job", side_effect=[None, {"output": remote_output}]) as poll_mock,
        ):
            output = run_network_extraction(
                image_array=image_array,
                params={"method": "snow2", "queue_name": "extraction-runpod"},
                voxel_size=1.0,
                endpoint_url="http://example:3100",
            )

        self.assertEqual(output, remote_output)
        submit_mock.assert_called_once()
        submit_kwargs = submit_mock.call_args.kwargs
        self.assertEqual(submit_kwargs["analysis_type"], "network_extraction")
        self.assertEqual(submit_kwargs["endpoint_url"], "http://example:3100")
        self.assertIn("image_npy_b64", submit_kwargs["payload"])
        self.assertIn("params", submit_kwargs["payload"])
        self.assertEqual(poll_mock.call_count, 2)
