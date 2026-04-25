from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from collections.abc import Iterable
from typing import Any

import httpx
from django.conf import settings
from django.core.cache import cache

log = logging.getLogger(__name__)

_OPENAPI_CACHE_KEY = "runpod:pods:openapi:options"
_OPENAPI_STALE_CACHE_KEY = "runpod:pods:openapi:stale"

_DEFAULT_PORTS = ["8888/http", "22/tcp"]
_ALLOWED_COMPUTE_TYPES = {"GPU", "CPU"}
_ALLOWED_CLOUD_TYPES = {"SECURE", "COMMUNITY"}
_ALLOWED_PORT_PROTOCOLS = {"http", "https", "tcp", "udp"}

_PORT_RE = re.compile(r"^\s*(?P<port>\d{1,5})\s*/\s*(?P<protocol>[A-Za-z]+)\s*$")
_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class RunPodError(Exception):
    """Base exception type for normalized RunPod service errors."""

    retryable = False

    def __init__(
        self,
        message: str,
        *,
        retryable: bool | None = None,
        status_code: int | None = None,
        details: Any = None,
    ) -> None:
        super().__init__(message)
        if retryable is not None:
            self.retryable = retryable
        self.status_code = status_code
        self.details = details


class RunPodConfigurationError(RunPodError):
    pass


class RunPodAuthError(RunPodError):
    pass


class RunPodValidationError(RunPodError):
    pass


class RunPodCapacityError(RunPodError):
    pass


class RunPodTransientError(RunPodError):
    retryable = True


class RunPodNotFoundError(RunPodError):
    pass


class RunPodAPIError(RunPodError):
    pass


def default_creation_options() -> dict[str, Any]:
    default_cloud = str(getattr(settings, "RUNPOD_DEFAULT_CLOUD_TYPE", "SECURE") or "SECURE").upper()
    default_compute = str(getattr(settings, "RUNPOD_DEFAULT_COMPUTE_TYPE", "GPU") or "GPU").upper()
    cloud_types = sorted(_ALLOWED_CLOUD_TYPES)
    compute_types = sorted(_ALLOWED_COMPUTE_TYPES)
    return {
        "gpu_type_ids": [],
        "cpu_flavor_ids": [],
        "data_center_ids": [],
        "allowed_cuda_versions": [],
        "cloud_types": cloud_types,
        "compute_types": compute_types,
        "default_cloud_type": default_cloud if default_cloud in cloud_types else "SECURE",
        "default_compute_type": default_compute if default_compute in compute_types else "GPU",
        "schema_fields": {
            "name": "name",
            "image_name": "imageName",
            "cloud_type": "cloudType",
            "compute_type": "computeType",
            "gpu_type_id": "gpuTypeId",
            "cpu_flavor_id": "cpuFlavorId",
            "data_center_id": "dataCenterId",
            "allowed_cuda_version": "cudaVersion",
            "ports": "ports",
            "env": "env",
            "interruptible": "interruptible",
            "registry_auth_id": "containerRegistryAuthId",
        },
        "schema_field_types": {
            "gpu_type_id": "string",
            "cpu_flavor_id": "string",
            "data_center_id": "string",
            "allowed_cuda_version": "string",
            "ports": "array",
            "env": "object",
        },
        "source": "fallback",
    }


def _get_api_base_url() -> str:
    return str(getattr(settings, "RUNPOD_API_BASE_URL", "https://rest.runpod.io/v1") or "").rstrip("/")


def _get_api_key() -> str:
    return str(getattr(settings, "RUNPOD_API_KEY", "") or "").strip()


def _get_default_ports() -> list[str]:
    raw = getattr(settings, "RUNPOD_DEFAULT_PORTS", _DEFAULT_PORTS)
    if isinstance(raw, str):
        return [entry.strip() for entry in raw.split(",") if entry.strip()]
    if isinstance(raw, Iterable):
        return [str(entry).strip() for entry in raw if str(entry).strip()]
    return list(_DEFAULT_PORTS)


def _retry_count() -> int:
    return max(0, int(getattr(settings, "RUNPOD_RETRY_COUNT", 2)))


def _retry_backoff_seconds() -> float:
    return max(0.0, float(getattr(settings, "RUNPOD_RETRY_BACKOFF_SECONDS", 0.5)))


def _idempotency_ttl_seconds() -> int:
    return max(30, int(getattr(settings, "RUNPOD_IDEMPOTENCY_TTL_SECONDS", 600)))


def _options_cache_ttl_seconds() -> int:
    return max(30, int(getattr(settings, "RUNPOD_OPTIONS_CACHE_TTL_SECONDS", 900)))


def _timeout() -> httpx.Timeout:
    timeout = float(getattr(settings, "RUNPOD_HTTP_TIMEOUT_SECONDS", 20.0))
    connect = float(getattr(settings, "RUNPOD_CONNECT_TIMEOUT_SECONDS", 5.0))
    return httpx.Timeout(timeout=timeout, connect=connect)


def _headers(*, require_auth: bool) -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    api_key = _get_api_key()
    if require_auth:
        if not api_key:
            raise RunPodConfigurationError("RUNPOD_API_KEY is not configured.")
        headers["Authorization"] = f"Bearer {api_key}"
    elif api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _request_json(
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    expected_statuses: set[int] | None = None,
    require_auth: bool = True,
) -> dict[str, Any] | list[Any] | None:
    expected = expected_statuses or {200}
    base_url = _get_api_base_url()
    if not base_url:
        raise RunPodConfigurationError("RUNPOD_API_BASE_URL is not configured.")

    url = f"{base_url}{path}"
    retry_count = _retry_count()
    backoff = _retry_backoff_seconds()

    for attempt in range(retry_count + 1):
        try:
            with httpx.Client(timeout=_timeout()) as client:
                response = client.request(method, url, json=body, headers=_headers(require_auth=require_auth))
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_attempt = attempt == retry_count
            if last_attempt:
                raise RunPodTransientError(
                    f"RunPod request failed after retries: {method} {path}",
                    retryable=True,
                ) from exc
            time.sleep(backoff * (2**attempt))
            continue

        if response.status_code in expected:
            if not response.content:
                return None
            try:
                parsed = response.json()
            except ValueError as exc:
                raise RunPodAPIError(f"RunPod returned non-JSON response for {method} {path}.") from exc
            if isinstance(parsed, (dict, list)):
                return parsed
            return None

        error = _map_http_error(path=path, response=response)
        if error.retryable and attempt < retry_count:
            time.sleep(backoff * (2**attempt))
            continue
        raise error

    raise RunPodTransientError(f"RunPod request exhausted retries for {method} {path}.", retryable=True)


def _extract_error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = None

    if isinstance(payload, dict):
        for key in ("message", "error", "detail"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return json.dumps(payload)

    text = (response.text or "").strip()
    return text or f"RunPod API returned HTTP {response.status_code}."


def _map_http_error(*, path: str, response: httpx.Response) -> RunPodError:
    message = _extract_error_message(response)
    status = response.status_code
    lowered = message.lower()

    if status in {401, 403}:
        return RunPodAuthError(f"RunPod authentication failed: {message}", status_code=status)

    if status == 404:
        return RunPodNotFoundError(f"RunPod resource not found for {path}.", status_code=status)

    if status in {400, 422}:
        if "capacity" in lowered or "quota" in lowered or "out of stock" in lowered:
            return RunPodCapacityError(f"RunPod capacity error: {message}", status_code=status)
        return RunPodValidationError(f"RunPod rejected the request: {message}", status_code=status)

    if status == 429 or 500 <= status < 600:
        return RunPodTransientError(
            f"RunPod transient error (HTTP {status}): {message}",
            retryable=True,
            status_code=status,
        )

    return RunPodAPIError(f"RunPod API error (HTTP {status}): {message}", status_code=status)


def _first_non_empty(raw: dict[str, Any], keys: Iterable[str], default: str = "") -> str:
    for key in keys:
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float)):
            return str(value)
    return default


def _extract_pod_list(payload: dict[str, Any] | list[Any] | None) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("pods", "data", "items"):
        maybe = payload.get(key)
        if isinstance(maybe, list):
            return [item for item in maybe if isinstance(item, dict)]
    return []


def _extract_pod_payload(payload: dict[str, Any] | list[Any] | None) -> dict[str, Any]:
    if isinstance(payload, dict):
        for key in ("pod", "data", "item"):
            maybe = payload.get(key)
            if isinstance(maybe, dict):
                return maybe
        return payload
    return {}


def _normalize_pod(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": _first_non_empty(raw, ("id", "podId")),
        "name": _first_non_empty(raw, ("name", "podName")),
        "status": _first_non_empty(raw, ("status", "desiredStatus", "machineStatus"), default="unknown"),
        "image_name": _first_non_empty(raw, ("imageName", "image")),
        "cloud_type": _first_non_empty(raw, ("cloudType",)),
        "compute_type": _first_non_empty(raw, ("computeType",)),
        "gpu_type_id": _first_non_empty(raw, ("gpuTypeId", "gpuType")),
        "cpu_flavor_id": _first_non_empty(raw, ("cpuFlavorId", "cpuFlavor")),
        "data_center_id": _first_non_empty(raw, ("dataCenterId", "dataCenter")),
        "interruptible": bool(raw.get("interruptible", False)),
        "desired_status": _first_non_empty(raw, ("desiredStatus",)),
    }


def list_pods() -> list[dict[str, Any]]:
    payload = _request_json("GET", "/pods", expected_statuses={200})
    pods = [_normalize_pod(item) for item in _extract_pod_list(payload)]
    return [pod for pod in pods if pod["id"]]


def _resolve_ref(ref: str, schemas: dict[str, Any]) -> dict[str, Any]:
    prefix = "#/components/schemas/"
    if not ref.startswith(prefix):
        return {}
    key = ref[len(prefix) :]
    resolved = schemas.get(key)
    return resolved if isinstance(resolved, dict) else {}


def _merge_schema_properties(schema: dict[str, Any], schemas: dict[str, Any]) -> dict[str, Any]:
    if "$ref" in schema and isinstance(schema["$ref"], str):
        schema = _resolve_ref(schema["$ref"], schemas)

    merged: dict[str, Any] = {}
    for chunk in schema.get("allOf", []):
        if isinstance(chunk, dict):
            merged.update(_merge_schema_properties(chunk, schemas))

    properties = schema.get("properties")
    if isinstance(properties, dict):
        merged.update({key: value for key, value in properties.items() if isinstance(value, dict)})
    return merged


def _extract_enum(property_schema: dict[str, Any]) -> list[str]:
    if "enum" in property_schema and isinstance(property_schema["enum"], list):
        return [str(item) for item in property_schema["enum"] if str(item).strip()]

    items = property_schema.get("items")
    if isinstance(items, dict) and isinstance(items.get("enum"), list):
        return [str(item) for item in items["enum"] if str(item).strip()]

    return []


def _pick_schema_field(properties: dict[str, Any], candidates: tuple[str, ...], default: str) -> str:
    for candidate in candidates:
        if candidate in properties:
            return candidate
    return default


def _extract_creation_options_from_openapi(openapi: dict[str, Any]) -> dict[str, Any]:
    components = openapi.get("components") if isinstance(openapi.get("components"), dict) else {}
    schemas = components.get("schemas") if isinstance(components.get("schemas"), dict) else {}

    pod_create = schemas.get("PodCreateInput")
    if not isinstance(pod_create, dict):
        for key, value in schemas.items():
            if isinstance(value, dict) and "podcreateinput" in key.lower():
                pod_create = value
                break

    if not isinstance(pod_create, dict):
        return default_creation_options()

    properties = _merge_schema_properties(pod_create, schemas)

    gpu_enum = _extract_enum(properties.get("gpuTypeIds", {})) or _extract_enum(properties.get("gpuTypeId", {}))
    cpu_enum = _extract_enum(properties.get("cpuFlavorIds", {})) or _extract_enum(properties.get("cpuFlavorId", {}))
    dc_enum = _extract_enum(properties.get("dataCenterIds", {})) or _extract_enum(properties.get("dataCenterId", {}))
    cuda_enum = _extract_enum(properties.get("allowedCudaVersions", {})) or _extract_enum(
        properties.get("cudaVersion", {})
    )

    cloud_enum = _extract_enum(properties.get("cloudType", {})) or sorted(_ALLOWED_CLOUD_TYPES)
    compute_enum = _extract_enum(properties.get("computeType", {})) or sorted(_ALLOWED_COMPUTE_TYPES)

    schema_fields = {
        "name": _pick_schema_field(properties, ("name",), "name"),
        "image_name": _pick_schema_field(properties, ("imageName", "image"), "imageName"),
        "cloud_type": _pick_schema_field(properties, ("cloudType",), "cloudType"),
        "compute_type": _pick_schema_field(properties, ("computeType",), "computeType"),
        "gpu_type_id": _pick_schema_field(properties, ("gpuTypeId", "gpuTypeIds"), "gpuTypeId"),
        "cpu_flavor_id": _pick_schema_field(properties, ("cpuFlavorId", "cpuFlavorIds"), "cpuFlavorId"),
        "data_center_id": _pick_schema_field(properties, ("dataCenterId", "dataCenterIds"), "dataCenterId"),
        "allowed_cuda_version": _pick_schema_field(
            properties,
            ("cudaVersion", "allowedCudaVersions"),
            "cudaVersion",
        ),
        "ports": _pick_schema_field(properties, ("ports",), "ports"),
        "env": _pick_schema_field(properties, ("env", "environment"), "env"),
        "interruptible": _pick_schema_field(properties, ("interruptible",), "interruptible"),
        "registry_auth_id": _pick_schema_field(
            properties,
            ("containerRegistryAuthId", "containerRegistryAuth"),
            "containerRegistryAuthId",
        ),
    }

    schema_field_types = {
        "gpu_type_id": str(properties.get(schema_fields["gpu_type_id"], {}).get("type") or "string"),
        "cpu_flavor_id": str(properties.get(schema_fields["cpu_flavor_id"], {}).get("type") or "string"),
        "data_center_id": str(properties.get(schema_fields["data_center_id"], {}).get("type") or "string"),
        "allowed_cuda_version": str(
            properties.get(schema_fields["allowed_cuda_version"], {}).get("type") or "string"
        ),
        "ports": str(properties.get(schema_fields["ports"], {}).get("type") or "array"),
        "env": str(properties.get(schema_fields["env"], {}).get("type") or "object"),
    }

    defaults = default_creation_options()
    return {
        "gpu_type_ids": sorted(set(gpu_enum)),
        "cpu_flavor_ids": sorted(set(cpu_enum)),
        "data_center_ids": sorted(set(dc_enum)),
        "allowed_cuda_versions": sorted(set(cuda_enum)),
        "cloud_types": sorted(set(cloud_enum)) or defaults["cloud_types"],
        "compute_types": sorted(set(compute_enum)) or defaults["compute_types"],
        "default_cloud_type": defaults["default_cloud_type"],
        "default_compute_type": defaults["default_compute_type"],
        "schema_fields": schema_fields,
        "schema_field_types": schema_field_types,
        "source": "openapi",
    }


def get_creation_options(*, force_refresh: bool = False) -> dict[str, Any]:
    if not force_refresh:
        cached = cache.get(_OPENAPI_CACHE_KEY)
        if isinstance(cached, dict):
            return cached

    defaults = default_creation_options()

    try:
        openapi_payload = _request_json("GET", "/openapi.json", expected_statuses={200}, require_auth=False)
        if not isinstance(openapi_payload, dict):
            raise RunPodAPIError("RunPod openapi.json response was not an object.")
        parsed = _extract_creation_options_from_openapi(openapi_payload)
        cache.set(_OPENAPI_CACHE_KEY, parsed, timeout=_options_cache_ttl_seconds())
        cache.set(_OPENAPI_STALE_CACHE_KEY, parsed, timeout=7 * 24 * 60 * 60)
        return parsed
    except RunPodError as exc:
        stale = cache.get(_OPENAPI_STALE_CACHE_KEY)
        if isinstance(stale, dict):
            stale_with_source = dict(stale)
            stale_with_source["source"] = "stale-cache"
            stale_with_source["warning"] = str(exc)
            return stale_with_source

        defaults["warning"] = str(exc)
        return defaults


def parse_port_mappings(raw_ports: str | Iterable[str] | None) -> list[str]:
    if raw_ports is None:
        raw_entries = _get_default_ports()
    elif isinstance(raw_ports, str):
        raw_entries = [part.strip() for part in re.split(r"[\n,]", raw_ports) if part.strip()]
    else:
        raw_entries = [str(part).strip() for part in raw_ports if str(part).strip()]

    parsed: list[str] = []
    for entry in raw_entries:
        match = _PORT_RE.match(entry)
        if not match:
            raise RunPodValidationError(f"Invalid port mapping '{entry}'. Use values like '8888/http' or '22/tcp'.")

        port = int(match.group("port"))
        if port < 1 or port > 65535:
            raise RunPodValidationError(f"Port out of range in mapping '{entry}'.")

        protocol = match.group("protocol").lower()
        if protocol not in _ALLOWED_PORT_PROTOCOLS:
            raise RunPodValidationError(
                f"Unsupported protocol '{protocol}'. Allowed: {', '.join(sorted(_ALLOWED_PORT_PROTOCOLS))}."
            )

        parsed.append(f"{port}/{protocol}")

    if not parsed:
        raise RunPodValidationError("At least one port mapping is required.")

    return parsed


def parse_env_entries(raw_env: str | Iterable[str] | dict[str, Any] | None) -> dict[str, str]:
    if raw_env is None:
        return {}

    if isinstance(raw_env, dict):
        normalized: dict[str, str] = {}
        for key, value in raw_env.items():
            key_str = str(key).strip()
            if not key_str:
                continue
            if not _ENV_KEY_RE.match(key_str):
                raise RunPodValidationError(f"Invalid environment variable key '{key_str}'.")
            normalized[key_str] = str(value)
        return normalized

    if isinstance(raw_env, str):
        entries = [line.strip() for line in raw_env.splitlines() if line.strip()]
    else:
        entries = [str(line).strip() for line in raw_env if str(line).strip()]

    env_map: dict[str, str] = {}
    for entry in entries:
        if "=" not in entry:
            raise RunPodValidationError(f"Invalid env entry '{entry}'. Use KEY=VALUE format.")
        key, value = entry.split("=", 1)
        key = key.strip()
        if not _ENV_KEY_RE.match(key):
            raise RunPodValidationError(f"Invalid environment variable key '{key}'.")
        env_map[key] = value

    return env_map


def _build_env_payload(env_map: dict[str, str], env_type: str) -> Any:
    if not env_map:
        return {} if env_type == "object" else []

    if env_type == "array":
        return [{"key": key, "value": value} for key, value in env_map.items()]

    if env_type == "string":
        return "\n".join(f"{key}={value}" for key, value in env_map.items())

    return env_map


def _build_ports_payload(port_entries: list[str], ports_type: str) -> Any:
    if ports_type == "string":
        return ",".join(port_entries)
    return port_entries


def _coerce_scalar_field(value: str, declared_type: str) -> Any:
    if declared_type == "array":
        return [value]
    return value


def _resolve_field_type(field_types: dict[str, Any], semantic_key: str, schema_field_name: str) -> str:
    declared = str(field_types.get(semantic_key) or "").strip().lower()
    if declared:
        return declared

    # Backward-compatible inference for cached OpenAPI options generated before
    # scalar field type metadata existed for these keys.
    lowered_name = str(schema_field_name or "").strip().lower()
    if lowered_name.endswith("ids") or lowered_name.endswith("versions"):
        return "array"

    return "string"


def _resolve_registry_auth_id() -> str | None:
    configured_id = str(getattr(settings, "RUNPOD_REGISTRY_AUTH_ID", "") or "").strip()
    if configured_id:
        return configured_id

    username = str(getattr(settings, "RUNPOD_REGISTRY_USERNAME", "") or "").strip()
    token = str(getattr(settings, "RUNPOD_REGISTRY_PAT", "") or "").strip()
    if not username or not token:
        return None

    listing = _request_json("GET", "/containerregistryauth", expected_statuses={200}, require_auth=True)
    items: list[dict[str, Any]] = []
    if isinstance(listing, list):
        items = [item for item in listing if isinstance(item, dict)]
    elif isinstance(listing, dict):
        maybe = listing.get("containerRegistryAuth") or listing.get("items") or listing.get("data")
        if isinstance(maybe, list):
            items = [item for item in maybe if isinstance(item, dict)]

    for item in items:
        if _first_non_empty(item, ("username", "userName")) == username:
            existing = _first_non_empty(item, ("id", "containerRegistryAuthId"))
            if existing:
                return existing

    created = _request_json(
        "POST",
        "/containerregistryauth",
        body={
            "username": username,
            "password": token,
            "registry": "ghcr.io",
            "isDefault": False,
        },
        expected_statuses={200, 201},
        require_auth=True,
    )
    created_item = _extract_pod_payload(created)
    created_id = _first_non_empty(created_item, ("id", "containerRegistryAuthId"))
    if not created_id:
        raise RunPodAPIError("RunPod did not return a registry auth id after creating container registry auth.")
    return created_id


def _pick_required_string(spec: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = spec.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise RunPodValidationError(f"Missing required value for one of: {', '.join(keys)}")


def _pick_optional_string(spec: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = spec.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _build_pod_create_payload(spec: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
    pod_name = _pick_required_string(spec, "pod_name", "name")
    image_name = _pick_optional_string(spec, "image_name", "image")

    compute_type = str(spec.get("compute_type") or options.get("default_compute_type") or "GPU").strip().upper()
    cloud_type = str(spec.get("cloud_type") or options.get("default_cloud_type") or "SECURE").strip().upper()

    if compute_type not in _ALLOWED_COMPUTE_TYPES:
        raise RunPodValidationError("Compute type must be either GPU or CPU.")
    if cloud_type not in _ALLOWED_CLOUD_TYPES:
        raise RunPodValidationError("Cloud type must be either SECURE or COMMUNITY.")

    gpu_type_id = str(spec.get("gpu_type_id") or "").strip()
    cpu_flavor_id = str(spec.get("cpu_flavor_id") or "").strip()

    if compute_type == "GPU" and not gpu_type_id:
        raise RunPodValidationError("GPU compute type requires a GPU type.")
    if compute_type == "CPU" and not cpu_flavor_id:
        raise RunPodValidationError("CPU compute type requires a CPU flavor.")

    data_center_id = str(spec.get("data_center_id") or "").strip()
    cuda_version = str(spec.get("allowed_cuda_version") or "").strip()
    interruptible = bool(spec.get("interruptible", False))

    port_entries = parse_port_mappings(spec.get("ports", _get_default_ports()))
    env_map = parse_env_entries(spec.get("env_vars") or spec.get("env"))

    registry_auth_id = _resolve_registry_auth_id()

    fields = options.get("schema_fields") or default_creation_options()["schema_fields"]
    field_types = options.get("schema_field_types") or default_creation_options()["schema_field_types"]

    payload: dict[str, Any] = {
        fields["name"]: pod_name,
        fields["cloud_type"]: cloud_type,
        fields["compute_type"]: compute_type,
        fields["ports"]: _build_ports_payload(port_entries, str(field_types.get("ports") or "array")),
        fields["env"]: _build_env_payload(env_map, str(field_types.get("env") or "object")),
        fields["interruptible"]: interruptible,
    }

    if image_name:
        payload[fields["image_name"]] = image_name

    if gpu_type_id:
        payload[fields["gpu_type_id"]] = _coerce_scalar_field(
            gpu_type_id,
            _resolve_field_type(field_types, "gpu_type_id", fields["gpu_type_id"]),
        )
    if cpu_flavor_id:
        payload[fields["cpu_flavor_id"]] = _coerce_scalar_field(
            cpu_flavor_id,
            _resolve_field_type(field_types, "cpu_flavor_id", fields["cpu_flavor_id"]),
        )
    if data_center_id:
        payload[fields["data_center_id"]] = _coerce_scalar_field(
            data_center_id,
            _resolve_field_type(field_types, "data_center_id", fields["data_center_id"]),
        )
    if cuda_version:
        payload[fields["allowed_cuda_version"]] = _coerce_scalar_field(
            cuda_version,
            _resolve_field_type(field_types, "allowed_cuda_version", fields["allowed_cuda_version"]),
        )
    if registry_auth_id:
        payload[fields["registry_auth_id"]] = registry_auth_id

    return payload


def _create_idempotency_key(spec: dict[str, Any]) -> str:
    payload = {
        "pod_name": str(spec.get("pod_name") or spec.get("name") or "").strip(),
        "image_name": str(spec.get("image_name") or spec.get("image") or "").strip(),
        "compute_type": str(spec.get("compute_type") or "").strip().upper(),
        "gpu_type_id": str(spec.get("gpu_type_id") or "").strip(),
        "cpu_flavor_id": str(spec.get("cpu_flavor_id") or "").strip(),
        "data_center_id": str(spec.get("data_center_id") or "").strip(),
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return f"runpod:create:{digest}"


def create_pod(spec: dict[str, Any], *, idempotency_key: str | None = None) -> dict[str, Any]:
    key = idempotency_key or _create_idempotency_key(spec)
    cached = cache.get(key)
    if isinstance(cached, dict):
        result = dict(cached)
        result["idempotent"] = True
        return result

    pod_name = str(spec.get("pod_name") or spec.get("name") or "").strip()
    if not pod_name:
        raise RunPodValidationError("Pod name is required.")

    for existing in list_pods():
        if existing.get("name") == pod_name:
            existing_result = dict(existing)
            existing_result["idempotent"] = True
            cache.set(key, existing_result, timeout=_idempotency_ttl_seconds())
            return existing_result

    options = get_creation_options()
    payload = _build_pod_create_payload(spec, options)
    created = _request_json("POST", "/pods", body=payload, expected_statuses={200, 201})
    normalized = _normalize_pod(_extract_pod_payload(created))
    if not normalized.get("id"):
        raise RunPodAPIError("RunPod create pod response did not contain a pod id.")

    cache.set(key, normalized, timeout=_idempotency_ttl_seconds())
    return normalized


def _pod_action(pod_id: str, action: str) -> dict[str, Any]:
    normalized_id = pod_id.strip()
    if not normalized_id:
        raise RunPodValidationError("Pod id is required.")

    data = _request_json("POST", f"/pods/{normalized_id}/{action}", expected_statuses={200, 202, 204})
    if isinstance(data, dict):
        pod_payload = _extract_pod_payload(data)
        if pod_payload:
            return _normalize_pod(pod_payload)

    return {
        "id": normalized_id,
        "status": "pending",
        "action": action,
    }


def pause_pod(pod_id: str) -> dict[str, Any]:
    return _pod_action(pod_id, "stop")


def resume_pod(pod_id: str) -> dict[str, Any]:
    return _pod_action(pod_id, "start")


def terminate_pod(pod_id: str) -> dict[str, Any]:
    normalized_id = pod_id.strip()
    if not normalized_id:
        raise RunPodValidationError("Pod id is required.")

    try:
        _request_json("DELETE", f"/pods/{normalized_id}", expected_statuses={200, 202, 204})
    except RunPodNotFoundError:
        return {
            "id": normalized_id,
            "terminated": False,
            "idempotent": True,
        }

    return {
        "id": normalized_id,
        "terminated": True,
        "idempotent": False,
    }


def ensure_pod_exists(spec: dict[str, Any], *, idempotency_key: str | None = None) -> dict[str, Any]:
    """Programmatic orchestration helper for workers to ensure a pod exists."""
    return create_pod(spec, idempotency_key=idempotency_key)


def pause_idle_pod(pod_id: str) -> dict[str, Any]:
    """Programmatic orchestration helper for workers to pause an idle pod."""
    return pause_pod(pod_id)


def terminate_broken_pod(pod_id: str) -> dict[str, Any]:
    """Programmatic orchestration helper for workers to terminate an unhealthy pod."""
    return terminate_pod(pod_id)


__all__ = [
    "RunPodError",
    "RunPodConfigurationError",
    "RunPodAuthError",
    "RunPodValidationError",
    "RunPodCapacityError",
    "RunPodTransientError",
    "RunPodNotFoundError",
    "RunPodAPIError",
    "default_creation_options",
    "get_creation_options",
    "parse_port_mappings",
    "parse_env_entries",
    "list_pods",
    "create_pod",
    "pause_pod",
    "resume_pod",
    "terminate_pod",
    "ensure_pod_exists",
    "pause_idle_pod",
    "terminate_broken_pod",
]
