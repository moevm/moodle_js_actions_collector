#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")/.."
command -v docker >/dev/null || { echo "Docker is not installed." >&2; exit 1; }
[ -f .env ] || { echo "Start the local stack first: bash scripts/start.sh" >&2; exit 1; }
export E2E_IMAGE="${E2E_IMAGE:-moodle-actions-playwright:local}"
export E2E_UID="$(id -u)" E2E_GID="$(id -g)"
build=1
dockerfile=e2e/Dockerfile
network_args=()
case "${1:-}" in
  --no-build) build=0; shift ;;
  --offline)
    dockerfile=e2e/Dockerfile.offline
    network_args=(--network=none)
    [ -d e2e/npm-cache ] || { echo "Offline dependency archives are missing in e2e/npm-cache." >&2; exit 1; }
    shift ;;
esac
docker compose --profile test config --quiet
mkdir -p reports/e2e
# Export only the demo links, without mounting Moodle's entire data volume.
docker compose exec -T moodle cat /var/www/moodledata/demo.json > reports/e2e/demo.json.tmp
mv reports/e2e/demo.json.tmp reports/e2e/demo.json
if [ "$build" = 1 ]; then
  docker build --pull=false "${network_args[@]}" --tag "$E2E_IMAGE" --file "$dockerfile" e2e
fi
# Reuse the existing stack; never rebuild or recreate application services here.
status=0
docker compose --profile test run --rm --no-deps -T --pull never tests "$@" || status=$?
printf '\nE2E report: reports/e2e/html/index.html\n'
exit "$status"
