#!/usr/bin/env sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
ENV_FILE="$ROOT/config/.env"
if [ ! -f "$ENV_FILE" ]; then
    umask 077
    PASSWORD=$(od -An -N32 -tx1 /dev/urandom | tr -d ' \n')
    sed "s/CHANGE_ME_RANDOM_HEX_PASSWORD/$PASSWORD/" "$ROOT/config/.env.example" > "$ENV_FILE"
    printf '%s\n' "Created config/.env with a random database password."
    printf '%s\n' "Configure LLM_BASE_URL and LLM_MODEL there to enable your local model."
fi
if grep -q '^POSTGRES_PASSWORD=CHANGE_ME' "$ENV_FILE"; then
    printf '%s\n' "Replace POSTGRES_PASSWORD in config/.env with a random hexadecimal password first." >&2
    exit 1
fi
docker compose --env-file "$ENV_FILE" -f "$ROOT/config/compose.yaml" up --build -d --wait
printf '%s\n' "Chessmate started. Default URL: http://localhost:8080"
