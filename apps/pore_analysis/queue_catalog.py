from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

_CATALOG_CACHE: dict[str, Any] | None = None
_CATALOG_CACHE_PATH: str | None = None
_CATALOG_CACHE_MTIME_NS: int | None = None


class QueueCatalogError(Exception):
    """Raised when queue catalog configuration is invalid."""


class QueuePricingNotConfiguredError(QueueCatalogError):
    """Raised when a selected queue is missing pricing configuration."""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_catalog_path() -> Path:
    return _repo_root() / "config" / "queues.yaml"


def _as_non_empty_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise QueueCatalogError(f"Queue catalog field '{field_name}' must be a string.")
    normalized = value.strip()
    if not normalized:
        raise QueueCatalogError(f"Queue catalog field '{field_name}' cannot be empty.")
    return normalized


def _as_bool(value: Any, field_name: str, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    raise QueueCatalogError(f"Queue catalog field '{field_name}' must be a boolean.")


def _as_decimal(value: Any, field_name: str) -> Decimal:
    try:
        normalized = Decimal(str(value))
    except (InvalidOperation, TypeError) as exc:
        raise QueueCatalogError(f"Queue catalog field '{field_name}' must be numeric.") from exc

    if normalized < 0:
        raise QueueCatalogError(f"Queue catalog field '{field_name}' must be >= 0.")
    return normalized


def _normalize_pricing(raw_pricing: Any, *, queue_name: str) -> dict[str, Any]:
    if not isinstance(raw_pricing, dict):
        raise QueueCatalogError(f"Queue '{queue_name}' must define a pricing object.")

    if "default_credits_per_million_voxels" not in raw_pricing:
        raise QueueCatalogError(f"Queue '{queue_name}' is missing pricing.default_credits_per_million_voxels.")

    default_rate = _as_decimal(
        raw_pricing.get("default_credits_per_million_voxels"),
        f"queues[{queue_name}].pricing.default_credits_per_million_voxels",
    )

    overrides_raw = raw_pricing.get("analysis_credits_per_million_voxels", {})
    if not isinstance(overrides_raw, dict):
        raise QueueCatalogError(f"Queue '{queue_name}' pricing.analysis_credits_per_million_voxels must be a mapping.")

    overrides: dict[str, Decimal] = {}
    for analysis_type, value in overrides_raw.items():
        overrides[_as_non_empty_str(analysis_type, "analysis_type")] = _as_decimal(
            value,
            f"queues[{queue_name}].pricing.analysis_credits_per_million_voxels.{analysis_type}",
        )

    return {
        "default_credits_per_million_voxels": default_rate,
        "analysis_credits_per_million_voxels": overrides,
    }


def _normalize_queue_entry(raw_queue: Any) -> dict[str, Any]:
    if not isinstance(raw_queue, dict):
        raise QueueCatalogError("Each queue entry must be an object.")

    queue_name = _as_non_empty_str(raw_queue.get("name"), "name")
    display_name = str(raw_queue.get("display_name") or queue_name).strip() or queue_name
    backend_key = _as_non_empty_str(raw_queue.get("backend_key"), f"queues[{queue_name}].backend_key")
    compute_system = _as_non_empty_str(raw_queue.get("compute_system"), f"queues[{queue_name}].compute_system")

    analyses_raw = raw_queue.get("analyses")
    if not isinstance(analyses_raw, list) or not analyses_raw:
        raise QueueCatalogError(f"Queue '{queue_name}' must declare a non-empty analyses list.")
    analyses = [_as_non_empty_str(item, f"queues[{queue_name}].analyses") for item in analyses_raw]

    endpoint_raw = raw_queue.get("endpoint_url", "")
    endpoint_url = "" if endpoint_raw is None else str(endpoint_raw).strip()
    enabled = _as_bool(raw_queue.get("enabled"), f"queues[{queue_name}].enabled", default=True)

    capabilities_raw = raw_queue.get("capabilities", [])
    if not isinstance(capabilities_raw, list):
        raise QueueCatalogError(f"Queue '{queue_name}' capabilities must be a list.")
    capabilities = {_as_non_empty_str(item, f"queues[{queue_name}].capabilities") for item in capabilities_raw}

    pricing = _normalize_pricing(raw_queue.get("pricing"), queue_name=queue_name)

    return {
        "name": queue_name,
        "display_name": display_name,
        "backend_key": backend_key,
        "compute_system": compute_system,
        "analyses": analyses,
        "endpoint_url": endpoint_url,
        "enabled": enabled,
        "capabilities": capabilities,
        "pricing": pricing,
    }


def load_queue_catalog(path: str | Path) -> dict[str, Any]:
    catalog_path = Path(path)
    if not catalog_path.exists():
        raise QueueCatalogError(f"Queue catalog file does not exist: {catalog_path}")

    try:
        with catalog_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError as exc:
        raise QueueCatalogError(f"Failed to parse queue catalog YAML: {exc}") from exc

    if not isinstance(data, dict):
        raise QueueCatalogError("Queue catalog root must be a mapping.")

    version = data.get("version")
    if version != 1:
        raise QueueCatalogError("Queue catalog version must be 1.")

    queues_raw = data.get("queues")
    if not isinstance(queues_raw, list) or not queues_raw:
        raise QueueCatalogError("Queue catalog must define a non-empty 'queues' list.")

    normalized_queues: list[dict[str, Any]] = []
    queues_by_name: dict[str, dict[str, Any]] = {}

    for raw_queue in queues_raw:
        queue_entry = _normalize_queue_entry(raw_queue)
        queue_name = queue_entry["name"]
        if queue_name in queues_by_name:
            raise QueueCatalogError(f"Duplicate queue name '{queue_name}' in queue catalog.")
        normalized_queues.append(queue_entry)
        queues_by_name[queue_name] = queue_entry

    analysis_defaults_raw = data.get("analysis_defaults", {})
    if not isinstance(analysis_defaults_raw, dict):
        raise QueueCatalogError("Queue catalog field 'analysis_defaults' must be a mapping.")

    analysis_defaults: dict[str, str] = {}
    for analysis_type, queue_name_raw in analysis_defaults_raw.items():
        analysis_name = _as_non_empty_str(analysis_type, "analysis_defaults.analysis_type")
        queue_name = _as_non_empty_str(queue_name_raw, f"analysis_defaults.{analysis_name}")

        queue = queues_by_name.get(queue_name)
        if queue is None:
            raise QueueCatalogError(f"analysis_defaults.{analysis_name} references unknown queue '{queue_name}'.")
        if not queue["enabled"]:
            raise QueueCatalogError(f"analysis_defaults.{analysis_name} references disabled queue '{queue_name}'.")
        if analysis_name not in queue["analyses"]:
            raise QueueCatalogError(
                f"analysis_defaults.{analysis_name} points to queue '{queue_name}' which does not support the analysis."
            )

        analysis_defaults[analysis_name] = queue_name

    return {
        "version": version,
        "queues": normalized_queues,
        "queues_by_name": queues_by_name,
        "analysis_defaults": analysis_defaults,
    }


def _get_catalog() -> dict[str, Any]:
    from django.conf import settings

    global _CATALOG_CACHE, _CATALOG_CACHE_MTIME_NS, _CATALOG_CACHE_PATH

    catalog_path = Path(getattr(settings, "QUEUE_CATALOG_PATH", default_catalog_path()))
    catalog_path_key = str(catalog_path)

    try:
        mtime_ns = catalog_path.stat().st_mtime_ns
    except FileNotFoundError as exc:
        raise QueueCatalogError(f"Queue catalog file does not exist: {catalog_path}") from exc

    if (
        _CATALOG_CACHE is not None
        and catalog_path_key == _CATALOG_CACHE_PATH
        and mtime_ns == _CATALOG_CACHE_MTIME_NS
    ):
        return _CATALOG_CACHE

    try:
        catalog = load_queue_catalog(catalog_path)
    except QueueCatalogError:
        if _CATALOG_CACHE is not None and catalog_path_key == _CATALOG_CACHE_PATH:
            log.warning(
                "Queue catalog reload failed for %s; using previous in-memory catalog.",
                catalog_path,
                exc_info=True,
            )
            return _CATALOG_CACHE
        raise

    _CATALOG_CACHE = catalog
    _CATALOG_CACHE_PATH = catalog_path_key
    _CATALOG_CACHE_MTIME_NS = mtime_ns

    # Keep settings in sync for code paths that inspect settings.QUEUE_CATALOG directly.
    settings.QUEUE_CATALOG = catalog
    return catalog


def get_enabled_queues(*, analysis_type: str | None = None) -> list[dict[str, Any]]:
    catalog = _get_catalog()
    queues: list[dict[str, Any]] = []

    for queue in catalog.get("queues", []):
        if not queue.get("enabled", True):
            continue
        if analysis_type and analysis_type not in queue.get("analyses", []):
            continue
        queues.append(queue)

    return queues


def get_queue_choices_for_analysis(analysis_type: str) -> list[tuple[str, str]]:
    queues = get_enabled_queues(analysis_type=analysis_type)
    return [(queue["name"], queue.get("display_name") or queue["name"]) for queue in queues]


def get_default_queue_for_analysis(analysis_type: str) -> str:
    catalog = _get_catalog()
    configured = catalog.get("analysis_defaults", {}).get(analysis_type)
    if configured:
        return configured

    choices = get_queue_choices_for_analysis(analysis_type)
    if not choices:
        raise QueueCatalogError(f"No enabled queues are configured for analysis '{analysis_type}'.")
    return choices[0][0]


def get_queue_config(queue_name: str) -> dict[str, Any]:
    catalog = _get_catalog()
    queue = catalog.get("queues_by_name", {}).get(queue_name)
    if queue is None:
        raise QueueCatalogError(f"Unknown queue '{queue_name}'.")
    return queue


def queue_supports_analysis(queue_name: str, analysis_type: str) -> bool:
    queue = get_queue_config(queue_name)
    return analysis_type in queue.get("analyses", [])


def get_queue_backend(queue_name: str) -> str:
    queue = get_queue_config(queue_name)
    return str(queue.get("backend_key") or "default")


def get_queue_endpoint(queue_name: str, *, default: str = "") -> str:
    queue = get_queue_config(queue_name)
    endpoint = str(queue.get("endpoint_url") or "").strip()
    compute_system = str(queue.get("compute_system") or "").strip()

    try:
        from django.conf import settings

        override_maps = {
            "julia": getattr(settings, "JULIA_QUEUE_ENDPOINTS", {}),
            "taichi": getattr(settings, "TAICHI_QUEUE_ENDPOINTS", {}),
            "cpu": getattr(settings, "PYTHON_REMOTE_QUEUE_ENDPOINTS", {}),
        }
        override_map = override_maps.get(compute_system) or {}
        override_endpoint = str(override_map.get(queue_name) or "").strip()
        if override_endpoint:
            return override_endpoint
    except Exception:
        # During early startup, settings may not be ready; fall back to catalog/default.
        pass

    return endpoint or default


def get_queue_capabilities(queue_name: str) -> set[str]:
    queue = get_queue_config(queue_name)
    return set(queue.get("capabilities") or set())


def get_parallel_queues_for_analysis(analysis_type: str) -> set[str]:
    queue_names: set[str] = set()
    for queue in get_enabled_queues(analysis_type=analysis_type):
        capabilities = set(queue.get("capabilities") or set())
        if "parallel" in capabilities:
            queue_names.add(queue["name"])
    return queue_names


def get_queue_pricing_rate(queue_name: str, analysis_type: str) -> Decimal:
    queue = get_queue_config(queue_name)
    if analysis_type not in queue.get("analyses", []):
        raise QueuePricingNotConfiguredError(f"Queue '{queue_name}' is not configured for analysis '{analysis_type}'.")

    pricing = queue.get("pricing") or {}
    overrides = pricing.get("analysis_credits_per_million_voxels") or {}
    if analysis_type in overrides:
        return overrides[analysis_type]

    default_rate = pricing.get("default_credits_per_million_voxels")
    if default_rate is None:
        raise QueuePricingNotConfiguredError(f"Queue '{queue_name}' has no default pricing configured.")

    return default_rate


def build_backend_queue_map(catalog: dict[str, Any], compute_system: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for queue in catalog.get("queues", []):
        if not queue.get("enabled", True):
            continue
        if queue.get("compute_system") != compute_system:
            continue
        backend_key = str(queue.get("backend_key") or "default")
        mapping.setdefault(backend_key, queue["name"])
    return mapping


def build_queue_endpoint_map(catalog: dict[str, Any], compute_system: str) -> dict[str, str]:
    endpoints: dict[str, str] = {}
    for queue in catalog.get("queues", []):
        if not queue.get("enabled", True):
            continue
        if queue.get("compute_system") != compute_system:
            continue
        endpoint = str(queue.get("endpoint_url") or "").strip()
        if endpoint:
            endpoints[queue["name"]] = endpoint
    return endpoints
