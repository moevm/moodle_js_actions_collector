#!/usr/bin/env bash
# Export activity only; user/password records are not exported.
set -euo pipefail
cd -- "$(dirname -- "$0")"
export_dir="exports/$(date +%Y%m%d-%H%M%S)-$$"
mkdir -p "$export_dir"
for collection in statistics sessions; do
  docker compose exec -T -e EXPORT_COLLECTION="$collection" mongodb sh -c '
    exec mongoexport --host 127.0.0.1 \
      --username "$MONGO_INITDB_ROOT_USERNAME" \
      --password "$MONGO_INITDB_ROOT_PASSWORD" \
      --authenticationDatabase admin \
      --db "$MONGO_INITDB_DATABASE" --collection "$EXPORT_COLLECTION"
  ' > "$export_dir/$collection.json"
done
printf 'Export saved to %s\n' "$export_dir"
