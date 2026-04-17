#!/usr/bin/env bash
# exit on error
set -o errexit

export DJANGO_SETTINGS_MODULE=poromics.settings_production

echo "Installing python dependencies"
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env
uv sync --frozen --no-group dev --group prod
# update the path to use the right python/gunicorn, etc. from the local env
export PATH="${PWD}/.venv/bin:$PATH"

echo "Building JS & CSS"
npm install
npm run build

echo "Collecting staticfiles"
python manage.py collectstatic --noinput

echo "Running database migrations"
python manage.py migrate
