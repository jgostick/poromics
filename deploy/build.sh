#!/usr/bin/env bash
# exit on error
set -o errexit

export DJANGO_SETTINGS_MODULE=poromics.settings_production

echo "Installing python dependencies"
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env

# Pin interpreter for dependency resolution so builds don't float to newer
# Python versions that may lack binary wheels for native deps (for example taichi).
# Render disallows interpreter downloads in this environment, so use only system Python.
UV_PYTHON_VERSION="${PYTHON_VERSION:-3.12.8}"
uv sync --frozen --no-group dev --group prod --python "${UV_PYTHON_VERSION}" --python-preference only-system
# update the path to use the right python/gunicorn, etc. from the local env
export PATH="${PWD}/.venv/bin:$PATH"

echo "Building JS & CSS"
npm install
npm run build

echo "Collecting staticfiles"
python manage.py collectstatic --noinput

echo "Running database migrations"
python manage.py migrate
