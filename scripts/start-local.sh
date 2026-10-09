#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")/.."
command -v docker >/dev/null || { echo "Docker is not installed." >&2; exit 1; }
[ -f .env ] || cp .env.example .env
docker compose config --quiet
# Restart already built services; never download or build images.
if ! docker compose up -d --no-build --pull never --wait --wait-timeout 900; then
  docker compose ps -a
  docker compose logs --tail=80 moodle backend frontend
  exit 1
fi
printf '\nReady. See .env and README.md for URLs and credentials.\n'
