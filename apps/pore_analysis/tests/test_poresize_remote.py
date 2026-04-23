import sys
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from django.test import SimpleTestCase

from apps.pore_analysis.analysis.pore_size_distribution import compute_poresize_solution, run_poresize


class PoreSizeDistributionTests(SimpleTestCase):
    def test_compute_poresize_solution_returns_expected_structure(self):
        image_array = np.array(
            [
                [[True, False], [True, True]],
                [[False, True], [True, False]],
            ],
            dtype=bool,
        )

        fake_porespy = SimpleNamespace(
            filters=SimpleNamespace(
                local_thickness=lambda im, method, sizes, smooth: np.where(im, 2.0, 0.0),
            )
        )

        with patch.dict(sys.modules, {"porespy": fake_porespy}):
            solution = compute_poresize_solution(image_array=image_array, sizes=4, voxel_size=1.5)

        self.assertEqual(set(solution.keys()), {"counts", "bin_edges", "sizes", "voxel_size"})
        self.assertEqual(solution["sizes"], 4)
        self.assertEqual(solution["voxel_size"], 1.5)
        self.assertEqual(len(solution["counts"]), 4)
        self.assertEqual(len(solution["bin_edges"]), 5)

    @patch("apps.pore_analysis.analysis.pore_size_distribution.time.sleep", return_value=None)
    def test_run_poresize_remote_path_returns_remote_solution(self, _sleep):
        image_array = np.ones((2, 2, 2), dtype=bool)
        remote_solution = {
            "counts": [0.25, 0.75],
            "bin_edges": [0.0, 1.0, 2.0],
            "sizes": 2,
            "voxel_size": 1.0,
        }

        with (
            patch("python_remote_client.submit_job", return_value="job-123") as submit_mock,
            patch("python_remote_client.poll_job", side_effect=[None, {"solution": remote_solution}]) as poll_mock,
        ):
            solution = run_poresize(
                image_array=image_array,
                sizes=2,
                voxel_size=1.0,
                endpoint_url="http://example:3100",
            )

        self.assertEqual(solution["remote_job_id"], "job-123")
        self.assertEqual(solution["counts"], remote_solution["counts"])
        self.assertEqual(solution["bin_edges"], remote_solution["bin_edges"])

        submit_mock.assert_called_once()
        submit_kwargs = submit_mock.call_args.kwargs
        self.assertEqual(submit_kwargs["analysis_type"], "poresize")
        self.assertEqual(submit_kwargs["endpoint_url"], "http://example:3100")
        self.assertIn("image_npy_b64", submit_kwargs["payload"])
        self.assertEqual(poll_mock.call_count, 2)
