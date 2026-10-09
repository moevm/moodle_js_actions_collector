#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")/.."
command -v docker >/dev/null || { echo "Install Docker Desktop or Docker Engine + Compose first." >&2; exit 1; }
[ -f .env ] || cp .env.example .env
docker compose version
docker compose up -d --build --wait --wait-timeout 900
printf '\nReady. See README.md for URLs and credentials.\n'
