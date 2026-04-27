FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TAICHI_BACKEND=gpu \
    LOG_LEVEL=INFO

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
    "kabs @ git+https://github.com/PMEAL/kabs@f4d770da785a63c22b22128b743624af6b7fd639" \
    "runpod>=1.7"

COPY taichi_serverless_handler.py ./

CMD ["python", "taichi_serverless_handler.py"]
