
import logging
import time

import numpy as np

log = logging.getLogger(__name__)

ANALYSIS_TYPE = "poresize"
POLL_INTERVAL = 5


def compute_poresize_solution(*, image_array: np.ndarray, sizes: int = 25, voxel_size: float = 1.0) -> dict:
    import porespy as ps

    lt = ps.filters.local_thickness(
        im=image_array,
        method="dt",
        sizes=sizes,
        smooth=False,
    )
    counts, bin_edges = np.histogram(lt[image_array] * voxel_size, bins=sizes, density=True)
    return {
        "counts": counts.tolist(),
        "bin_edges": bin_edges.tolist(),
        "sizes": int(sizes),
        "voxel_size": float(voxel_size),
    }


def run_poresize(*, image_array, sizes=25, voxel_size=1.0, endpoint_url: str | None = None) -> dict:
    if endpoint_url:
        from python_remote_client import encode_array, poll_job, submit_job

        payload = {
            "image_npy_b64": encode_array(image_array.astype(bool)),
            "sizes": int(sizes),
            "voxel_size": float(voxel_size),
        }

        job_id = submit_job(
            analysis_type=ANALYSIS_TYPE,
            payload=payload,
            endpoint_url=endpoint_url,
        )
        log.info("Python remote pore-size job submitted: %s endpoint=%s", job_id, endpoint_url)

        while True:
            result = poll_job(job_id=job_id, endpoint_url=endpoint_url)
            if result is not None:
                solution = result.get("solution") if isinstance(result, dict) else None
                if not isinstance(solution, dict):
                    raise RuntimeError("Python remote service returned an invalid pore-size solution payload.")
                solution.setdefault("remote_job_id", job_id)
                return solution
            time.sleep(POLL_INTERVAL)

    return compute_poresize_solution(
        image_array=image_array,
        sizes=int(sizes),
        voxel_size=float(voxel_size),
    )
