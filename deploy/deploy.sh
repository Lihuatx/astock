#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")"
if [ "$#" -eq 1 ]; then
  export ASTOCK_IMAGE="$1"
fi
docker compose pull
docker compose up -d
docker compose exec -T dashboard python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:18080/healthz', timeout=5)"
