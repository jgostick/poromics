import pickle
import time
from typing import Any

import numpy as np
import porespy as ps

ANALYSIS_TYPE = "network_extraction"
POLL_INTERVAL = 5


def _normalize_parallel_kw(params: dict[str, Any]) -> dict[str, Any] | None:
    parallel_kw = params.get("parallel_kw")
    if not parallel_kw:
        return None

    normalized = {
        "divs": parallel_kw.get("divs"),
        "cores": parallel_kw.get("cores"),
        "overlap": parallel_kw.get("overlap"),
    }
    return {k: v for k, v in normalized.items() if v is not None}


def _extract_net_dict(results: Any) -> dict[str, Any]:
    """Return the OpenPNM-style network dict from either dict or Results-like output."""
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


def _to_json_compatible(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(k): _to_json_compatible(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_json_compatible(item) for item in value]
    return value


def compute_network_extraction_output(
    image_array: np.ndarray,
    params: dict[str, Any],
    voxel_size: float = 1.0,
) -> dict[str, Any]:
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
        kwargs: dict[str, Any] = {
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
    return {
        "method": method,
        "net": net,
    }


def run_network_extraction(
    image_array: np.ndarray,
    params: dict[str, Any],
    voxel_size: float = 1.0,
    endpoint_url: str | None = None,
) -> dict[str, Any]:
    if endpoint_url:
        from python_remote_client import encode_array, poll_job, submit_job

        payload = {
            "image_npy_b64": encode_array(image_array.astype(bool)),
            "params": params,
            "voxel_size": float(voxel_size),
        }

        job_id = submit_job(
            analysis_type=ANALYSIS_TYPE,
            payload=payload,
            endpoint_url=endpoint_url,
        )

        while True:
            result = poll_job(job_id=job_id, endpoint_url=endpoint_url)
            if result is not None:
                output = result.get("output") if isinstance(result, dict) else None
                if not isinstance(output, dict):
                    raise RuntimeError("Python remote service returned an invalid network extraction payload.")
                return output
            time.sleep(POLL_INTERVAL)

    return _to_json_compatible(
        compute_network_extraction_output(
            image_array=image_array,
            params=params,
            voxel_size=voxel_size,
        )
    )


def serialize_net_payload(payload: dict[str, Any]) -> bytes:
    """Serialize a payload dictionary while preserving NumPy arrays."""
    return pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL)


def deserialize_net_payload(payload: bytes) -> dict[str, Any]:
    obj = pickle.loads(payload)
    if not isinstance(obj, dict):
        raise ValueError("Serialized network payload is not a dict.")
    return obj
