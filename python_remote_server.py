"""Generic remote Python analysis worker HTTP service.

This service accepts analysis jobs over HTTP, executes them asynchronously,
and exposes polling endpoints. Analyses are selected by an analysis_type key.
"""

from __future__ import annotations

import base64
import importlib
import io
import json
import logging
import os
import threading
import uuid
from collections.abc import Callable, Mapping
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
HANDLER_LOCK = threading.Lock()

ANALYSIS_HANDLERS: dict[str, Callable[[dict], dict]] = {}
HANDLER_SOURCES: dict[str, str] = {}


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


def register_handler(
    analysis_type: str,
    handler: Callable[[dict], dict],
    *,
    source: str,
) -> None:
    normalized = str(analysis_type).strip()
    if not normalized:
        raise ValueError("analysis_type must be a non-empty string")
    if not callable(handler):
        raise ValueError(f"Handler for analysis_type '{normalized}' is not callable")

    with HANDLER_LOCK:
        if normalized in ANALYSIS_HANDLERS:
            raise ValueError(f"Handler already registered for analysis_type '{normalized}'")
        ANALYSIS_HANDLERS[normalized] = handler
        HANDLER_SOURCES[normalized] = source


def register_handlers(handlers: Mapping[str, Callable[[dict], dict]], *, source: str) -> list[str]:
    registered: list[str] = []
    for analysis_type, handler in handlers.items():
        register_handler(str(analysis_type), handler, source=source)
        registered.append(str(analysis_type).strip())
    return registered


def list_registered_handlers() -> list[dict[str, str]]:
    with HANDLER_LOCK:
        names = sorted(ANALYSIS_HANDLERS)
        return [
            {
                "analysis_type": name,
                "source": HANDLER_SOURCES.get(name, "unknown"),
            }
            for name in names
        ]


def _env_bool(name: str, *, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default


def _configured_handler_modules() -> list[str]:
    raw = os.environ.get("PYTHON_REMOTE_HANDLER_MODULES", "")
    return [item.strip() for item in raw.split(",") if item.strip()]


def load_handler_modules(*, module_names: list[str] | None = None, strict: bool | None = None) -> dict[str, object]:
    names = module_names if module_names is not None else _configured_handler_modules()
    strict_mode = _env_bool("PYTHON_REMOTE_HANDLER_STRICT", default=False) if strict is None else strict

    registered: list[str] = []
    loaded_modules: list[str] = []
    errors: list[str] = []

    for module_name in names:
        try:
            module = importlib.import_module(module_name)
            loader = getattr(module, "get_handlers", None)
            if not callable(loader):
                raise ValueError(f"Module '{module_name}' must define callable get_handlers()")

            handlers = loader()
            if not isinstance(handlers, Mapping):
                raise ValueError(f"Module '{module_name}' get_handlers() must return a mapping")

            newly_registered = register_handlers(handlers, source=f"plugin:{module_name}")
            loaded_modules.append(module_name)
            registered.extend(newly_registered)
            log.info("Loaded handler module %s (%d handlers)", module_name, len(newly_registered))
        except Exception as exc:
            message = f"Failed loading handler module '{module_name}': {exc}"
            errors.append(message)
            if strict_mode:
                raise RuntimeError(message) from exc
            log.warning(message)

    return {
        "loaded_modules": loaded_modules,
        "registered_analysis_types": registered,
        "errors": errors,
        "strict": strict_mode,
    }


def _compute_poresize_solution(*, image_array: np.ndarray, sizes: int = 25, voxel_size: float = 1.0) -> dict:
    """Compute pore-size distribution without importing Django app modules.

    This keeps the remote worker standalone so it can run on machines that do
    not have the full Poromics Django package layout.
    """
    try:
        import porespy as ps
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Missing required package 'porespy' on remote server. "
            "Install dependencies before starting python_remote_server.py."
        ) from exc

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


def _normalize_parallel_kw(params: dict) -> dict | None:
    parallel_kw = params.get("parallel_kw")
    if not parallel_kw:
        return None

    normalized = {
        "divs": parallel_kw.get("divs"),
        "cores": parallel_kw.get("cores"),
        "overlap": parallel_kw.get("overlap"),
    }
    return {k: v for k, v in normalized.items() if v is not None}


def _extract_net_dict(results) -> dict:
    if isinstance(results, dict):
        if "net" in results and isinstance(results["net"], dict):
            return results["net"]
        if "network" in results and isinstance(results["network"], dict):
            return results["network"]
        if any(str(key).startswith(("pore.", "throat.")) for key in results):
            return results
    if hasattr(results, "network"):
        return dict(results.network)
    raise ValueError("Extraction output did not include a usable network dictionary.")


def _to_json_compatible(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(k): _to_json_compatible(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_json_compatible(item) for item in value]
    return value


def _compute_network_extraction_output(*, image_array: np.ndarray, params: dict, voxel_size: float = 1.0) -> dict:
    try:
        import porespy as ps
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Missing required package 'porespy' on remote server. "
            "Install dependencies before starting python_remote_server.py."
        ) from exc

    method = params.get("method", "snow2")
    parallel_kw = _normalize_parallel_kw(params)

    if method == "snow2":
        phases = image_array.astype(int)
        if phases.max() <= 0:
            phases = (image_array > 0).astype(int)

        results = ps.networks.snow2(
            phases=phases,
            boundary_width=int(params.get("boundary_width", 3)),
            accuracy=params.get("accuracy", "standard"),
            voxel_size=float(voxel_size),
            sigma=float(params.get("sigma", 0.4)),
            r_max=int(params.get("r_max", 4)),
            parallel_kw=parallel_kw,
        )
    elif method == "magnet":
        im = image_array.astype(bool)
        kwargs = {
            "parallel_kw": parallel_kw,
            "surface": bool(params.get("surface", False)),
            "voxel_size": float(voxel_size),
            "l_max": int(params.get("l_max", 7)),
            "throat_area": bool(params.get("throat_area", False)),
        }
        if params.get("s") is not None:
            kwargs["s"] = int(params["s"])
        if params.get("throat_junctions"):
            kwargs["throat_junctions"] = params["throat_junctions"]
        if kwargs["throat_area"]:
            kwargs["n_walkers"] = int(params.get("n_walkers", 10))
            kwargs["step_size"] = float(params.get("step_size", 0.5))
            if params.get("max_n_steps") is not None:
                kwargs["max_n_steps"] = int(params["max_n_steps"])

        results = ps.networks.magnet(im=im, **kwargs)
    else:
        raise ValueError(f"Unsupported extraction method: {method}")

    net = _extract_net_dict(results)
    return _to_json_compatible(
        {
            "method": method,
            "net": net,
        }
    )


def _handle_poresize(payload: dict) -> dict:
    image_npy_b64 = str(payload["image_npy_b64"])
    image_array = _decode_array(image_npy_b64).astype(bool)
    sizes = int(payload.get("sizes", 25))
    voxel_size = float(payload.get("voxel_size", 1.0))

    solution = _compute_poresize_solution(
        image_array=image_array,
        sizes=sizes,
        voxel_size=voxel_size,
    )
    return {"solution": solution}


def _handle_network_extraction(payload: dict) -> dict:
    image_npy_b64 = str(payload["image_npy_b64"])
    image_array = _decode_array(image_npy_b64).astype(bool)
    params = payload.get("params")
    if not isinstance(params, dict):
        raise ValueError("Missing required field: params")
    voxel_size = float(payload.get("voxel_size", 1.0))

    output = _compute_network_extraction_output(
        image_array=image_array,
        params=params,
        voxel_size=voxel_size,
    )
    return {"output": output}


def _register_builtin_handlers() -> None:
    register_handler("poresize", _handle_poresize, source="builtin:python_remote_server")
    register_handler("network_extraction", _handle_network_extraction, source="builtin:python_remote_server")


_register_builtin_handlers()


def _run_job(job_id: str, analysis_type: str, payload: dict) -> None:
    with JOB_LOCK:
        rec = JOB_STORE.get(job_id)
        if rec is None:
            return
        rec.status = "running"

    try:
        with HANDLER_LOCK:
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

        if self.path == "/handlers":
            return _json_response(
                self,
                200,
                {
                    "status": "ok",
                    "handlers": list_registered_handlers(),
                },
            )

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

    summary = load_handler_modules()
    log.info(
        "Handler registry initialized (builtin + plugins): loaded_modules=%d registered=%d errors=%d strict=%s",
        len(summary["loaded_modules"]),
        len(summary["registered_analysis_types"]),
        len(summary["errors"]),
        summary["strict"],
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
