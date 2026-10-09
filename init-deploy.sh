#!/usr/bin/env bash
# Compatibility entry point: collector only, no volume deletion.
set -euo pipefail
cd -- "$(dirname -- "$0")"
[ -f .env ] || cp .env.example .env
docker compose -f docker-compose.prod.yaml up -d --build --wait --wait-timeout 900
