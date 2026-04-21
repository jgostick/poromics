
import logging
import time

from kabs_permeability_core import compute_kabs_permeability_solution


log = logging.getLogger(__name__)

POLL_INTERVAL = 5


def run_kabs_permeability(
    *, image_array, direction, max_iterations, tolerance, backend, voxel_size, endpoint_url: str | None = None
):

    if endpoint_url:
        from taichi_client import poll_job, submit_job

        job_id = submit_job(
            image_array=image_array,
            direction=direction,
            max_iterations=max_iterations,
            tolerance=tolerance,
            backend=backend,
            voxel_size=voxel_size,
            endpoint_url=endpoint_url,
        )
        log.info("Taichi remote job submitted: %s endpoint=%s", job_id, endpoint_url)

        while True:
            result = poll_job(job_id=job_id, endpoint_url=endpoint_url)
            if result is not None:
                result.setdefault("remote_job_id", job_id)
                return result
            time.sleep(POLL_INTERVAL)

    return compute_kabs_permeability_solution(
        image_array=image_array,
        direction=direction,
        max_iterations=max_iterations,
        tolerance=tolerance,
        backend=backend,
        voxel_size=voxel_size,
    )
