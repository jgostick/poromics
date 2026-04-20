
import logging
import time


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

    from kabs import compute_permeability, solve_flow


    soln = solve_flow(
        im=image_array, 
        direction=direction,
        n_steps=max_iterations,
        tol=tolerance,
        verbose=False,
    )
    K = compute_permeability(
        soln=soln,
        direction=direction,
        dx_m=voxel_size,
    )

    solution = {
        "permeability [lu^2]": K["k_lu"],
        "direction": direction,
        "max_iterations": max_iterations,
        "tolerance": tolerance,
        "backend": backend,
        "voxel_size": voxel_size,
    }
    return solution
