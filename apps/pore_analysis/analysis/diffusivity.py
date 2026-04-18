import logging
import time

import numpy as np

log = logging.getLogger(__name__)

# How often (seconds) to poll the Julia server while waiting for a job to finish.
POLL_INTERVAL = 5


def run_julia_diffusivity(*, image_array: np.ndarray, direction: str, tolerance: float, backend: str) -> dict:
    """Submit a diffusivity calculation to the Julia tortuosity server and block until done.

    The Julia server must already be running and reachable at the configured port
    (JULIA_SERVER_PORT env var, default 2999).  This function is intended to be
    called from a Celery worker task, never from a Django request handler.

    Parameters
    ----------
    image_array : np.ndarray
        3-D (or 2-D) boolean pore-space array.
    direction : str
        Flow axis: "x", "y", or "z".
    tolerance : float
        Relative solver tolerance (e.g. 1e-5).
    backend : str
        "cpu" or "gpu".  Any value other than "gpu" is treated as CPU.

    Returns
    -------
    dict with keys:
        tortuosity            - scalar float
        effective_diffusivity - D_eff / D_0 = 1 / tortuosity (scalar float)
        direction             - axis used
        tolerance             - reltol used
        backend               - backend string

    Raises
    ------
    RuntimeError if the Julia server is unreachable or the job fails.
    """
    from julia_client import submit_job, poll_job

    use_gpu = backend.lower() == "gpu"
    arr = image_array.astype(bool)

    log.info(
        "Submitting diffusivity job: direction=%s tol=%s gpu=%s shape=%s",
        direction,
        tolerance,
        use_gpu,
        arr.shape,
    )
    job_id = submit_job(img=arr, axis=direction, reltol=float(tolerance), use_gpu=use_gpu)
    log.info("Julia job submitted: %s - polling every %ds", job_id, POLL_INTERVAL)

    while True:
        result = poll_job(job_id)
        if result is not None:
            break
        log.debug("Julia job %s still running, sleeping %ds", job_id, POLL_INTERVAL)
        time.sleep(POLL_INTERVAL)

    tau, _conc = result
    tau = float(tau)
    d_eff = 1.0 / tau if tau > 0 else 0.0

    log.info("Julia job %s complete: tortuosity=%.4f", job_id, tau)

    return {
        "tortuosity": tau,
        "effective_diffusivity": d_eff,
        "direction": direction,
        "tolerance": tolerance,
        "backend": backend,
    }
