#!/usr/bin/env bash
# Stops this project's containers, frees up whatever host ports the stack
# needs (killing any stray non-Docker process squatting on one, e.g. another
# local dev server also using port 3000), then starts the stack fresh.
set -euo pipefail

cd "$(dirname "$0")/backend"

echo "==> Stopping any existing containers for this project"
docker compose down

PORTS=$(grep -oE '"[0-9.]*:?[0-9]+:[0-9]+"' docker-compose.yml | tr -d '"' | awk -F: '{print $(NF-1)}' | sort -u)

echo "==> Freeing host ports: $(echo "$PORTS" | tr '\n' ' ')"
for port in $PORTS; do
  listing=$(lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | tail -n +2 || true)
  if [ -n "$listing" ]; then
    echo "$listing"
    echo "$listing" | awk '{print $2}' | sort -u | while read -r pid; do
      echo "    killing PID $pid (port $port)"
      kill -9 "$pid" 2>/dev/null || true
    done
  fi
done

echo "==> Starting containers"
docker compose up -d --build

docker compose ps
