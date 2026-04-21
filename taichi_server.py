"""Remote Taichi permeability worker HTTP service.

This service accepts permeability jobs over HTTP, executes them asynchronously
with local kabs/Taichi resources, and exposes status/result polling endpoints.
"""

import base64
import io
import json
import logging
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

log = logging.getLogger(__name__)


@dataclass
class JobRecord:
    status: str
    solution: dict | None = None
    error: str = ""


JOB_STORE: dict[str, JobRecord] = {}
JOB_LOCK = threading.Lock()
MAX_WORKERS = int(os.environ.get("TAICHI_SERVER_WORKERS", "2"))
EXECUTOR = ThreadPoolExecutor(max_workers=MAX_WORKERS)
_TAICHI_INIT_LOCK = threading.Lock()
_TAICHI_INITIALIZED = False
_TAICHI_BACKEND = ""


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _read_json(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0"))
    if length <= 0:
        raise ValueError("Empty request body")
    body = handler.rfile.read(length)
    data = json.loads(body.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Request body must be a JSON object")
    return data


def _decode_array(encoded_npy: str) -> np.ndarray:
    raw = base64.b64decode(encoded_npy)
    return np.load(io.BytesIO(raw), allow_pickle=False)


def _ensure_taichi_initialized(backend: str) -> None:
    global _TAICHI_INITIALIZED, _TAICHI_BACKEND

    if _TAICHI_INITIALIZED:
        return

    with _TAICHI_INIT_LOCK:
        if _TAICHI_INITIALIZED:
            return

        import taichi as ti

        configured_backend = (os.environ.get("TAICHI_BACKEND") or backend or "cpu").lower()
        arch_map = {
            "cpu": ti.cpu,
            "gpu": ti.gpu,
            "metal": ti.metal,
            "cuda": ti.cuda,
            "opengl": ti.opengl,
        }
        arch = arch_map.get(configured_backend, ti.cpu)
        ti.init(arch=arch)
        _TAICHI_BACKEND = configured_backend
        _TAICHI_INITIALIZED = True
        log.info("Taichi initialized for server backend=%s", configured_backend)


def _compute_permeability(payload: dict) -> dict:
    from kabs import compute_permeability, solve_flow

    image = _decode_array(str(payload["image_npy_b64"]))
    direction = str(payload["direction"])
    max_iterations = int(payload["max_iterations"])
    tolerance = float(payload["tolerance"])
    backend = str(payload["backend"])
    voxel_size = float(payload["voxel_size"])

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


def _run_job(job_id: str, payload: dict) -> None:
    with JOB_LOCK:
        rec = JOB_STORE.get(job_id)
        if rec is None:
            return
        rec.status = "running"

    try:
        solution = _compute_permeability(payload)
        with JOB_LOCK:
            rec = JOB_STORE.get(job_id)
            if rec is None:
                return
            rec.solution = solution
            rec.status = "done"
    except Exception as exc:
        with JOB_LOCK:
            rec = JOB_STORE.get(job_id)
            if rec is None:
                return
            rec.error = str(exc)
            rec.status = "error"
        log.exception("Taichi job %s failed", job_id)


class TaichiServerHandler(BaseHTTPRequestHandler):
    server_version = "TaichiServer/0.1"

    def log_message(self, format: str, *args):  # noqa: A003
        log.info("%s - %s", self.address_string(), format % args)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            return _json_response(self, 200, {"status": "ok", "workers": MAX_WORKERS})

        if self.path.startswith("/job/"):
            job_id = self.path.split("/", 2)[2]
            with JOB_LOCK:
                rec = JOB_STORE.get(job_id)
            if rec is None:
                return _json_response(self, 404, {"error": "unknown job"})
            if rec.status == "done":
                return _json_response(self, 200, {"status": "done", "solution": rec.solution})
            if rec.status == "error":
                return _json_response(self, 200, {"status": "error", "error": rec.error})
            return _json_response(self, 200, {"status": rec.status})

        return _json_response(self, 404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/permeability":
            return _json_response(self, 404, {"error": "not found"})

        try:
            payload = _read_json(self)
            required = {
                "image_npy_b64",
                "direction",
                "max_iterations",
                "tolerance",
                "backend",
                "voxel_size",
            }
            missing = sorted(required - set(payload))
            if missing:
                return _json_response(self, 400, {"error": f"Missing required fields: {', '.join(missing)}"})

            job_id = str(uuid.uuid4())
            with JOB_LOCK:
                JOB_STORE[job_id] = JobRecord(status="pending")
            EXECUTOR.submit(_run_job, job_id, payload)
            log.info("Taichi job queued: %s", job_id)
            return _json_response(self, 202, {"job_id": job_id})

        except Exception as exc:
            return _json_response(self, 400, {"error": str(exc)})

    def do_DELETE(self) -> None:  # noqa: N802
        if not self.path.startswith("/job/"):
            return _json_response(self, 404, {"error": "not found"})

        job_id = self.path.split("/", 2)[2]
        with JOB_LOCK:
            JOB_STORE.pop(job_id, None)
        self.send_response(204)
        self.end_headers()


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("TAICHI_SERVER_LOG_LEVEL", "INFO"),
        format="[%(asctime)s] %(levelname)s %(name)s %(message)s",
    )

    host = os.environ.get("TAICHI_SERVER_HOST", "127.0.0.1")
    port = int(os.environ.get("TAICHI_SERVER_PORT", "3000"))
    server = ThreadingHTTPServer((host, port), TaichiServerHandler)
    log.info("Taichi permeability server listening on %s:%s", host, port)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        EXECUTOR.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    main()
