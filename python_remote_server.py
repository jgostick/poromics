"""Generic remote Python analysis worker HTTP service.

This service accepts analysis jobs over HTTP, executes them asynchronously,
and exposes polling endpoints. Analyses are selected by an analysis_type key.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

log = logging.getLogger(__name__)


@dataclass
class JobRecord:
    status: str
    result: dict | None = None
    error: str = ""


JOB_STORE: dict[str, JobRecord] = {}
JOB_LOCK = threading.Lock()
MAX_WORKERS = int(os.environ.get("PYTHON_REMOTE_SERVER_WORKERS", "2"))
EXECUTOR = ThreadPoolExecutor(max_workers=MAX_WORKERS)


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


def _handle_poresize(payload: dict) -> dict:
    from apps.pore_analysis.analysis.pore_size_distribution import compute_poresize_solution

    image_npy_b64 = str(payload["image_npy_b64"])
    image_array = _decode_array(image_npy_b64).astype(bool)
    sizes = int(payload.get("sizes", 25))
    voxel_size = float(payload.get("voxel_size", 1.0))

    solution = compute_poresize_solution(
        image_array=image_array,
        sizes=sizes,
        voxel_size=voxel_size,
    )
    return {"solution": solution}


ANALYSIS_HANDLERS: dict[str, Callable[[dict], dict]] = {
    "poresize": _handle_poresize,
}


def _run_job(job_id: str, analysis_type: str, payload: dict) -> None:
    with JOB_LOCK:
        rec = JOB_STORE.get(job_id)
        if rec is None:
            return
        rec.status = "running"

    try:
        handler = ANALYSIS_HANDLERS.get(analysis_type)
        if handler is None:
            raise ValueError(f"Unsupported analysis_type: {analysis_type}")

        result = handler(payload)
        with JOB_LOCK:
            rec = JOB_STORE.get(job_id)
            if rec is None:
                return
            rec.result = result
            rec.status = "done"
    except Exception as exc:
        with JOB_LOCK:
            rec = JOB_STORE.get(job_id)
            if rec is None:
                return
            rec.error = str(exc)
            rec.status = "error"
        log.exception("Python remote job %s failed", job_id)


class PythonRemoteServerHandler(BaseHTTPRequestHandler):
    server_version = "PythonRemoteServer/0.1"

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
                return _json_response(self, 200, {"status": "done", "result": rec.result})
            if rec.status == "error":
                return _json_response(self, 200, {"status": "error", "error": rec.error})
            return _json_response(self, 200, {"status": rec.status})

        return _json_response(self, 404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/job":
            return _json_response(self, 404, {"error": "not found"})

        try:
            body = _read_json(self)
            analysis_type = str(body.get("analysis_type") or "").strip()
            payload = body.get("payload")
            if not analysis_type:
                return _json_response(self, 400, {"error": "Missing required field: analysis_type"})
            if not isinstance(payload, dict):
                return _json_response(self, 400, {"error": "Missing required field: payload"})

            job_id = str(uuid.uuid4())
            with JOB_LOCK:
                JOB_STORE[job_id] = JobRecord(status="pending")
            EXECUTOR.submit(_run_job, job_id, analysis_type, payload)
            log.info("Python remote job queued: %s analysis_type=%s", job_id, analysis_type)
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
        level=os.environ.get("PYTHON_REMOTE_SERVER_LOG_LEVEL", "INFO"),
        format="[%(asctime)s] %(levelname)s %(name)s %(message)s",
    )

    host = os.environ.get("PYTHON_REMOTE_SERVER_HOST", "127.0.0.1")
    port = int(os.environ.get("PYTHON_REMOTE_SERVER_PORT", "3100"))
    server = ThreadingHTTPServer((host, port), PythonRemoteServerHandler)
    log.info("Python remote server listening on %s:%s", host, port)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        EXECUTOR.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    main()
