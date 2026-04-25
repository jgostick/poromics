FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TAICHI_SERVER_HOST=0.0.0.0 \
    TAICHI_SERVER_PORT=3000 \
    TAICHI_SERVER_WORKERS=2 \
    TAICHI_SERVER_LOG_LEVEL=INFO \
    TAICHI_BACKEND=gpu

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    git \
    libgl1 \
    libx11-6 \
    libxext6 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

RUN uv pip install --system --no-cache \
    "numpy==2.4.4" \
    "taichi==1.7.4" \
    "kabs @ git+https://github.com/PMEAL/kabs@f4d770da785a63c22b22128b743624af6b7fd639"

COPY taichi_server.py ./

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://127.0.0.1:3000/health || exit 1

CMD ["python", "taichi_server.py"]
