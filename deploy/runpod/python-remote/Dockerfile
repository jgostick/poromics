FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHON_REMOTE_SERVER_HOST=0.0.0.0 \
    PYTHON_REMOTE_SERVER_PORT=3100 \
    PYTHON_REMOTE_SERVER_WORKERS=2 \
    PYTHON_REMOTE_SERVER_LOG_LEVEL=INFO \
    PYTHON_REMOTE_HANDLER_MODULES= \
    PYTHON_REMOTE_HANDLER_STRICT=false

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

RUN uv pip install --system --no-cache \
    "numpy==2.4.4" \
    "porespy==3.0.4"

COPY python_remote_server.py ./

EXPOSE 3100

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://127.0.0.1:3100/health || exit 1

CMD ["python", "python_remote_server.py"]
