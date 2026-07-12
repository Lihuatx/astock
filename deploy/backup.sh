#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")"
stamp="$(date +%Y%m%d-%H%M%S)"
mkdir -p data/backups
docker compose exec -T dashboard python -m astock.cli dashboard-backup --target "/app/server-data/backups/server-${stamp}.db"
tar -czf "data/backups/bundles-${stamp}.tgz" -C data bundles
docker compose images > "data/backups/manifest-${stamp}.txt"
find data/backups -type f -name 'server-*.db' -mtime +35 -print
