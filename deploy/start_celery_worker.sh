#!/usr/bin/env bash
set -o errexit
set -o nounset
set -o pipefail

QUEUE_CATALOG_PATH="${QUEUE_CATALOG_PATH:-config/queues.yaml}"

if [[ -x "${PWD}/.venv/bin/python" ]]; then
    PYTHON_BIN="${PWD}/.venv/bin/python"
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
else
    echo "No Python interpreter found in PATH." >&2
    exit 1
fi

QUEUE_LIST="$({
"${PYTHON_BIN}" - "$QUEUE_CATALOG_PATH" <<'PY'
import sys
from pathlib import Path

import yaml

catalog_path = Path(sys.argv[1])
if not catalog_path.exists():
    raise SystemExit(f"Queue catalog not found: {catalog_path}")

with catalog_path.open("r", encoding="utf-8") as f:
    catalog = yaml.safe_load(f) or {}

enabled_queues = []
for queue in catalog.get("queues", []):
    if not isinstance(queue, dict):
        continue
    if not queue.get("enabled", True):
        continue

    queue_name = str(queue.get("name") or "").strip()
    if queue_name:
        enabled_queues.append(queue_name)

if not enabled_queues:
    raise SystemExit("No enabled queues found in queue catalog.")

print(",".join(enabled_queues))
PY
} )"

echo "Resolved Celery queues from ${QUEUE_CATALOG_PATH}: ${QUEUE_LIST}"

if [[ "${CELERY_QUEUE_LIST_ONLY:-0}" == "1" ]]; then
    exit 0
fi

exec celery -A poromics worker \
    -l INFO \
    --pool "${CELERY_POOL:-threads}" \
    --concurrency "${CELERY_CONCURRENCY:-2}" \
    -Q "${QUEUE_LIST}"
