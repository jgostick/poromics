"""RunPod Serverless handler for Taichi permeability computation.

This file is the entrypoint for the taichi-runpod-serverless Docker image.
It uses the RunPod Python SDK to receive jobs from the RunPod Serverless platform,
run kabs permeability computation, and return the result.

Input format (job["input"]):
    image_npy_b64:  base64-encoded .npy file of a bool array
    direction:      "x" | "y" | "z"
    max_iterations: int
    tolerance:      float
    backend:        "cpu" | "gpu" | "cuda" | "metal" | "opengl"
    voxel_size:     float (metres per voxel)

Output format (returned dict, placed in job output by RunPod):
    permeability [lu^2]: float
    direction:           str
    max_iterations:      int
    tolerance:           float
    backend:             str
    voxel_size:          float

This mirrors the output of taichi_server.py's _compute_permeability() so that the Django
task layer can handle both pod and serverless results identically.

Usage (Docker CMD or entrypoint):
    python taichi_serverless_handler.py

Required packages (same as taichi_server.py image, plus runpod):
    runpod, taichi, kabs, numpy
"""

import base64
import io
import logging
import os
import threading

import numpy as np

log = logging.getLogger(__name__)

_TAICHI_INIT_LOCK = threading.Lock()
_TAICHI_INITIALIZED = False


def _ensure_taichi_initialized(backend: str) -> None:
    global _TAICHI_INITIALIZED

    if _TAICHI_INITIALIZED:
        return

    with _TAICHI_INIT_LOCK:
        if _TAICHI_INITIALIZED:
            return

        import taichi as ti

        configured_backend = (os.environ.get("TAICHI_BACKEND") or backend or "gpu").lower()
        arch_map = {
            "cpu": ti.cpu,
            "gpu": ti.gpu,
            "metal": ti.metal,
            "cuda": ti.cuda,
            "opengl": ti.opengl,
        }
        arch = arch_map.get(configured_backend, ti.gpu)
        ti.init(arch=arch)
        _TAICHI_INITIALIZED = True
        log.info("Taichi initialized (backend=%s)", configured_backend)


def _decode_array(encoded_npy: str) -> np.ndarray:
    raw = base64.b64decode(encoded_npy)
    return np.load(io.BytesIO(raw), allow_pickle=False)


def _compute_permeability(inp: dict) -> dict:
    """Run kabs permeability computation and return the solution dict."""
    from kabs import compute_permeability, solve_flow

    image = _decode_array(str(inp["image_npy_b64"]))
    direction = str(inp["direction"])
    max_iterations = int(inp["max_iterations"])
    tolerance = float(inp["tolerance"])
    backend = str(inp["backend"])
    voxel_size = float(inp["voxel_size"])

    _ensure_taichi_initialized(backend)

    solution_state = solve_flow(
        im=image,
        direction=direction,
        n_steps=max_iterations,
        tol=tolerance,
        verbose=False,
    )
    permeability = compute_permeability(
        soln=solution_state,
        direction=direction,
        dx_m=voxel_size,
    )

    return {
        "permeability [lu^2]": permeability["k_lu"],
        "direction": direction,
        "max_iterations": max_iterations,
        "tolerance": tolerance,
        "backend": backend,
        "voxel_size": voxel_size,
    }


def handler(job: dict) -> dict:
    """RunPod Serverless handler entry point.

    RunPod calls this function for each job.  The return value becomes the job's
    ``output`` field accessible via the status polling endpoint.

    Returning a dict signals success.  Raising an exception signals failure —
    RunPod will set the job status to FAILED and include the error message.
    """
    inp = job.get("input") or {}

    required = {"image_npy_b64", "direction", "max_iterations", "tolerance", "backend", "voxel_size"}
    missing = sorted(required - set(inp))
    if missing:
        raise ValueError(f"Missing required input fields: {', '.join(missing)}")

    log.info(
        "RunPod Serverless job %s: direction=%s, max_iterations=%s, backend=%s",
        job.get("id", "unknown"),
        inp.get("direction"),
        inp.get("max_iterations"),
        inp.get("backend"),
    )

    return _compute_permeability(inp)


if __name__ == "__main__":
    import runpod

    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="[%(asctime)s] %(levelname)s %(name)s %(message)s",
    )
    runpod.serverless.start({"handler": handler})
