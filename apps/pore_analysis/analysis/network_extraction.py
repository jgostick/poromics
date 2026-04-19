import json
from typing import Any

import numpy as np
import porespy as ps


def _jsonable_value(value: Any):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(k): _jsonable_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable_value(v) for v in value]
    return value


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


def run_network_extraction(image_array: np.ndarray, params: dict[str, Any], voxel_size: float = 1.0) -> dict[str, Any]:
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

    network = dict(results.network)
    return {
        "method": method,
        "network": network,
    }


def serialize_network_payload(payload: dict[str, Any]) -> bytes:
    return json.dumps(_jsonable_value(payload)).encode("utf-8")
