# RunPod Pod Images

This folder contains repo-owned Dockerfiles for the current long-running remote worker model.

These images are for RunPod pods or any other container host where you keep the worker process running.
They do not implement the future RunPod serverless transport.

## Images

### Python remote image

Path: `deploy/runpod/python-remote/Dockerfile`

This image runs `python_remote_server.py` and is the current fit for the CPU remote queues:

- `poresize-runpod`
- `extraction-runpod`

Build from the repository root:

```bash
docker build -f deploy/runpod/python-remote/Dockerfile -t poromics/python-remote:latest .
```

Run locally:

```bash
docker run --rm -p 3100:3100 \
  -e PYTHON_REMOTE_SERVER_WORKERS=2 \
  poromics/python-remote:latest
```

Health check:

```bash
curl http://127.0.0.1:3100/health
```

Point the Poromics app at the pod URL with queue-specific overrides:

```bash
PYTHON_REMOTE_QUEUE_ENDPOINTS=poresize-runpod=https://<RUNPOD_HOST>,extraction-runpod=https://<RUNPOD_HOST>
```

If you want to keep an existing queue name instead of the RunPod-named queue, point that queue at the same URL. The routing layer is queue-name to endpoint mapping.

### Taichi image

Path: `deploy/runpod/taichi/Dockerfile`

This image runs `taichi_server.py` for remote permeability execution.

Build from the repository root:

```bash
docker build --platform linux/amd64 -f deploy/runpod/taichi/Dockerfile -t poromics/taichi-remote:latest .
```

Run locally with CPU fallback:

```bash
docker run --rm --platform linux/amd64 -p 3000:3000 \
  -e TAICHI_BACKEND=cpu \
  poromics/taichi-remote:latest
```

Run on a GPU-backed host:

```bash
docker run --rm --platform linux/amd64 --gpus all -p 3000:3000 \
  -e TAICHI_BACKEND=gpu \
  poromics/taichi-remote:latest
```

Health check:

```bash
curl http://127.0.0.1:3000/health
```

Point the Poromics app at the pod URL with either the dedicated RunPod queue or an existing Taichi queue name:

```bash
TAICHI_QUEUE_ENDPOINTS=taichi-runpod=https://<RUNPOD_HOST>
```

or:

```bash
TAICHI_QUEUE_ENDPOINTS=kabs-gpu=https://<RUNPOD_HOST>
```

## GHCR Workflow

For RunPod pods, the usual path is:

1. Keep the Dockerfiles in this repo.
2. Build a Linux image from the Dockerfile.
3. Push that image to GitHub Container Registry.
4. Configure the RunPod pod to pull that image tag.

The Dockerfile is the recipe. The GHCR image tag is the deployable artifact that RunPod pulls.

### 1) Log in to GHCR

`ghcr.io` is the registry hostname used by Docker clients. It is not a useful browser login page.

Do the account and token setup on `github.com`, then authenticate from the terminal with `docker login ghcr.io`.

After you publish an image, view and manage it from the GitHub Packages UI:

- Personal account: profile -> Packages
- Organization: organization -> Packages
- Repository-linked package: repository sidebar -> Packages

Create a GitHub personal access token that can push packages.

For a classic token, `write:packages` is enough to push. If you want RunPod to pull a private package, also grant `read:packages` and configure registry credentials in RunPod.

If you are publishing into an organization namespace, you still log in as your GitHub user. The organization name is used in the image tag, not as the Docker login username.

Log in:

```bash
export GHCR_USER=<github-username>
export GHCR_NAMESPACE=<github-user-or-org>
export GHCR_TOKEN=<github-personal-access-token>
echo "$GHCR_TOKEN" | docker login ghcr.io -u "$GHCR_USER" --password-stdin
```

If Docker prompts interactively instead of using `--password-stdin`, enter:

- Username: your GitHub username
- Password: your GitHub personal access token (classic)

Do not use your normal GitHub website password for GHCR.

### 2) Build and push the Python remote image

Use `buildx` so the published image matches the Linux architecture expected by RunPod:

```bash
docker buildx build --platform linux/amd64 \
  -f deploy/runpod/python-remote/Dockerfile \
  -t ghcr.io/$GHCR_NAMESPACE/poromics-python-remote:latest \
  -t ghcr.io/$GHCR_NAMESPACE/poromics-python-remote:<version-or-git-sha> \
  --push .
```

### 3) Build and push the Taichi image

Taichi currently requires `linux/amd64` for Linux builds:

```bash
docker buildx build --platform linux/amd64 \
  -f deploy/runpod/taichi/Dockerfile \
  -t ghcr.io/$GHCR_NAMESPACE/poromics-taichi-remote:latest \
  -t ghcr.io/$GHCR_NAMESPACE/poromics-taichi-remote:<version-or-git-sha> \
  --push .
```

### 4) Point RunPod at the GHCR image

This step assumes you are using a RunPod pod that starts from a container image.

In that model, you do not start with a plain Ubuntu machine and then manually install the image from a shell. Instead, RunPod itself pulls the image tag and starts the container for you.

That means the GHCR image is the thing RunPod boots.

In the RunPod pod configuration, set the container image to one of the pushed tags, for example:

In the RunPod pod configuration, set the container image to one of the pushed tags, for example:

```text
ghcr.io/<github-user-or-org>/poromics-python-remote:latest
```

or:

```text
ghcr.io/<github-user-or-org>/poromics-taichi-remote:latest
```

RunPod can pull a private GHCR image, but only if you configure registry credentials correctly in RunPod. Making the package public is optional, not required.

### Alternate model: plain Ubuntu host

If instead you start with a normal Ubuntu server or VM, then your original mental model is correct:

1. Install Docker on that host.
2. Authenticate to GHCR if the image is private.
3. `docker pull` the image.
4. `docker run` the image.

That path is more manual, but it works fine if you want to treat RunPod like a generic remote Linux machine.

### What is inside the image?

The image includes the userspace environment needed to run the worker:

- a Linux base image filesystem
- Python
- installed Python dependencies
- the worker script
- the default command that starts the worker

For example, the Python remote worker image is built from `python:3.12-slim` and then adds the runtime packages and `python_remote_server.py`.

The image does not include a full VM or its own kernel. The host machine or RunPod pod runtime provides the Linux kernel, and the container runs on top of that.

So the practical rule is:

- RunPod pod image field: give RunPod the GHCR image tag directly
- Plain Ubuntu host: install Docker yourself, then `pull` and `run` the image manually

### 5) Wire the Poromics app to the RunPod endpoint

After the pod is running and you have its public base URL, point the Poromics services at that URL.

Python remote queues:

```bash
PYTHON_REMOTE_QUEUE_ENDPOINTS=poresize-runpod=https://<RUNPOD_HOST>,extraction-runpod=https://<RUNPOD_HOST>
```

Taichi queue:

```bash
TAICHI_QUEUE_ENDPOINTS=taichi-runpod=https://<RUNPOD_HOST>
```

If you prefer to keep existing queue names such as `kabs-gpu`, map that queue name to the same RunPod URL instead.

## Notes

- The Python remote image installs only the standalone runtime packages needed by `python_remote_server.py`, so it does not pull in the full Django app dependency set.
- Build and run the Taichi image with `--platform linux/amd64` because `taichi==1.7.4` does not publish Linux arm64 wheels. This keeps local builds on Apple Silicon aligned with the current RunPod target architecture.
- For actual deployments, prefer versioned or commit-based tags over `latest` so a pod can be reproduced exactly.
- `.dockerignore` at the repository root keeps local environments, media, and secrets out of the image build context.
- `git` is installed in the Taichi image because `kabs` is installed from its pinned Git commit.

## GHCR Troubleshooting

If RunPod cannot pull the image and shows an authorization error, check these first:

1. Package visibility. GHCR images are private by default after the first push. Private is fine, but then RunPod must have working GHCR pull credentials. Public visibility is optional.
2. Token type. Use a personal access token classic, not a fine-grained token.
3. Token scopes. For private pulls, ensure the token has at least `read:packages`. `write:packages` also works, but `read:packages` is the minimum needed for pulling.
4. Username versus namespace. Log in with your GitHub username. The image tag namespace can be your user or organization name.
5. Organization SSO. If the package belongs to an organization with SSO enabled, authorize the token for that organization.
6. Image tag exists. Confirm the exact tag exists in GitHub Packages, especially if RunPod is using `latest`.
