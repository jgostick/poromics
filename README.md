# Poromics

Network extraction as a service

## Quickstart

### Prerequisites

To run the app in the recommended configuration, you will need the following installed:
- [Docker](https://www.docker.com/get-started) and [Docker Compose](https://docs.docker.com/compose/install)
- [uv](https://docs.astral.sh/uv/getting-started/installation/) (for Python)
- [node and npm](https://docs.npmjs.com/downloading-and-installing-node-js-and-npm) (for JavaScript)

On Windows, you will also need to install `make`, which you can do by
[following these instructions](https://stackoverflow.com/a/57042516/8207).

### Initial setup

Run the following command to initialize your application:

```bash
make init
```

This will:

- Build and run your Postgres database
- Build and run your Redis database
- Run your database migrations
- Install front end dependencies

Then you can start the app:

```bash
make dev
```

This will run your Django server and build and run your front end (JavaScript and CSS) pipeline.

Your app should now be running! You can open it at [localhost:8000](http://localhost:8000/).

If you're just getting started, [try these steps next](https://docs.saaspegasus.com/getting-started/#post-installation-steps).

## Using the Makefile

You can run `make` to see other helper functions, and you can view the source
of the file in case you need to run any specific commands.

## Installation - Native

You can also install/run the app directly on your OS using the instructions below.

You can setup a virtual environment and install dependencies in a single command with:

```bash
uv sync
```

This will create your virtual environment in the `.venv` directory of your project root.

## Set up database

*If you are using Docker you can skip these steps.*

Create a database named `poromics`.

```
createdb poromics
```

Create database migrations:

```
uv run manage.py makemigrations
```

Create database tables:

```
uv run manage.py migrate
```

## Running server

```bash
uv run manage.py runserver
```

## Building front-end

To build JavaScript and CSS files, first install npm packages:

```bash
npm install
```

Then build (and watch for changes locally):

```bash
npm run dev
```

## Running Celery

Celery can be used to run background tasks.

Celery requires [Redis](https://redis.io/) as a message broker, so make sure
it is installed and running.

You can run it using:

```bash
celery -A poromics worker -l INFO --pool=solo
```

Or with celery beat (for scheduled tasks):

```bash
celery -A poromics worker -l INFO -B --pool=solo
```

Note: Using the `solo` pool is recommended for development but not for production.

## Remote Julia Server (PoC)

For diffusivity jobs, Celery can route to a Julia server running on another machine.

### 1) Configure queue and endpoint on the Mac (Django + Celery host)

Set these in `.env`:

```bash
# Optional default endpoint used when a queue has no explicit mapping
JULIA_DEFAULT_SERVER_URL=http://127.0.0.1:2999

# Route diffusivity "gpu" backend submissions to a custom queue name
JULIA_QUEUE_GPU=julia-gpu-remote1

# Map queue names to Julia HTTP endpoints
# Format: QUEUE=URL,QUEUE=URL
JULIA_QUEUE_ENDPOINTS=julia-gpu-remote1=http://192.168.1.50:2999
```

If you keep `JULIA_QUEUE_GPU=julia-gpu`, existing behavior remains local unless you map `julia-gpu` to a remote URL.

### 2) Run the Julia server on the remote machine

Copy the updated `julia_server.jl` file to the remote machine and start it with a LAN bind host:

```bash
export JULIA_SERVER_HOST=0.0.0.0
export JULIA_SERVER_PORT=2999
julia julia_server.jl
```

Then verify from the Mac:

```bash
curl http://192.168.1.50:2999/health
```

### 3) Start/restart services on the Mac

After updating `.env`, restart Django and Celery so new queue/endpoint settings are loaded.

### Notes

- Queue-to-endpoint routing is configured in Django settings via environment variables.
- This PoC keeps Celery workers on the Mac; only Julia execution moves to the remote host.
- Current setup is intended for trusted LAN use and does not add auth or TLS.

## Remote Taichi Server (PoC)

Permeability jobs can run remotely through a Taichi HTTP worker service.

### 1) Configure queue and endpoint on the Mac (Django + Celery host)

Set these in `.env`:

```bash
# Empty means permeability uses local in-process kabs execution.
TAICHI_DEFAULT_SERVER_URL=

# Route permeability "gpu" backend submissions to a custom queue name.
TAICHI_QUEUE_GPU=kabs-gpu-remote1

# Map queue names to Taichi HTTP endpoints.
# Format: QUEUE=URL,QUEUE=URL
TAICHI_QUEUE_ENDPOINTS=kabs-gpu-remote1=http://192.168.1.51:3000
```

If you keep `TAICHI_QUEUE_GPU=kabs-gpu`, existing local behavior remains unchanged unless you map `kabs-gpu` to a remote URL.

### 2) Run the Taichi server on the remote machine

Copy `taichi_server.py` to the remote machine and run:

```bash
export TAICHI_SERVER_HOST=0.0.0.0
export TAICHI_SERVER_PORT=3000
uv run python taichi_server.py
```

Then verify from the Mac:

```bash
curl http://192.168.1.51:3000/health
```

### 3) Start/restart services on the Mac

After updating `.env`, restart Django and Celery so the queue mapping is reloaded.

### Notes

- Queue-to-endpoint routing for Taichi is settings-driven, same as Julia.
- If a queue has no configured endpoint, permeability runs locally in the Celery worker.
- This PoC is intended for trusted LAN use and does not add auth or TLS.

## Updating translations

**Using make:**

```bash
make translations
```

**Native:**

```bash
uv run manage.py makemessages --all --ignore node_modules --ignore .venv
uv run manage.py makemessages -d djangojs --all --ignore node_modules --ignore .venv
uv run manage.py compilemessages --ignore .venv
```

## Google Authentication Setup

To setup Google Authentication, follow the [instructions here](https://docs.allauth.org/en/latest/socialaccount/providers/google.html).

## Github Authentication Setup

To setup Github Authentication, follow the [instructions here](https://docs.allauth.org/en/latest/socialaccount/providers/github.html).

## Installing Git commit hooks

To install the Git commit hooks run the following:

```shell
uv run pre-commit install --install-hooks
```

Once these are installed they will be run on every commit.

For more information see the [docs](https://docs.saaspegasus.com/code-structure#code-formatting).

## Running Tests

To run tests:

**Using make:**

```bash
make test
```

**Native:**

```bash
uv run manage.py test
```

Or to test a specific app/module:

**Using make:**

```bash
make test ARGS='apps.web.tests.test_basic_views --keepdb'
```

**Native:**

```bash
uv run manage.py test apps.web.tests.test_basic_views --keepdb
```

On Linux-based systems you can watch for changes using the following:

```bash
find . -name '*.py' | entr uv run manage.py test apps.web.tests.test_basic_views
```
