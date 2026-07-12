#!/usr/bin/env sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "usage: rollback.sh <previous-image-tag>" >&2
  exit 2
fi

cd "$(dirname "$0")"
export ASTOCK_IMAGE="$1"
docker compose pull dashboard
docker compose up -d dashboard
docker compose exec -T dashboard python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=5)"
