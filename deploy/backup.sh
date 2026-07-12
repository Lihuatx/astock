#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")"
stamp="$(date +%Y%m%d-%H%M%S)"
mkdir -p data/backups
docker compose exec -T dashboard python -m astock.cli dashboard-backup --target "/app/server-data/backups/${stamp}"
find data/backups -mindepth 1 -maxdepth 1 -type d -mtime +35 -print
