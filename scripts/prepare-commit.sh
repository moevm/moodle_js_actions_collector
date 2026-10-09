#!/usr/bin/env bash
# Use after overlaying the archive onto an existing checkout.
# Move obsolete files aside; preserve .git, .env and database volumes.
set -euo pipefail
cd -- "$(dirname -- "$0")/.."
backup_dir=".commit-backup/$(date +%Y%m%d-%H%M%S)-$$"
for path in local-test docker-compose.local.yaml docker-compose.test.yaml init-test.sh init-mongo.js MOODLE_QUIZ_FIX.md client/Dockerfile.source .github/workflows/selenium.yml; do
  if [ -e "$path" ]; then
    mkdir -p "$backup_dir/$(dirname -- "$path")"
    mv -- "$path" "$backup_dir/$path"
  fi
done
find . -type d \( -name .git -o -name node_modules -o -name .commit-backup \) -prune -o -type f -name '*Zone.Identifier*' -print0 |
while IFS= read -r -d '' path; do
  mkdir -p "$backup_dir/$(dirname -- "$path")"
  mv -- "$path" "$backup_dir/$path"
done
printf 'Obsolete files moved to %s if any were present. No containers or volumes were changed.\n' "$backup_dir"
