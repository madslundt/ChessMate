#!/usr/bin/env sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
PYTHON=${PYTHON:-"$ROOT/.venv/bin/python"}
if [ ! -x "$PYTHON" ]; then PYTHON=python3; fi
"$PYTHON" -m pytest tests -q
npm --prefix src/frontend run build
npm --prefix src/frontend test
docker compose --env-file config/.env.example -f config/compose.yaml config --quiet
printf '%s\n' "Backend tests, frontend production build/unit tests, and Compose configuration passed."
