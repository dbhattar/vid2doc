#!/usr/bin/env bash
# Stops this project's containers, frees up whatever host ports the stack
# needs (killing any stray non-Docker process squatting on one, e.g. another
# local dev server also using port 3000), then starts the stack fresh.
#
# --dev: also (re)starts the Stripe CLI webhook listener in the background,
# forwarding to the local api container -- without this, Stripe has nowhere
# to deliver checkout/webhook events during local testing, so wallet top-ups
# silently never credit (see backend/README.md's Billing section). Not
# needed in production, where a real Stripe Dashboard webhook endpoint
# delivers directly to the public URL instead.
set -euo pipefail

DEV_MODE=false
for arg in "$@"; do
  case "$arg" in
    --dev) DEV_MODE=true ;;
  esac
done

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

if [ "$DEV_MODE" = true ]; then
  echo "==> --dev: (re)starting Stripe CLI webhook listener"
  pkill -f "stripe listen --forward-to" 2>/dev/null || true

  if ! command -v stripe >/dev/null 2>&1; then
    echo "    Stripe CLI not found -- skipping. Install: https://docs.stripe.com/stripe-cli"
  else
    STRIPE_LOG="/tmp/framewrite-stripe-listen.log"
    nohup stripe listen --forward-to localhost:8000/api/billing/webhook > "$STRIPE_LOG" 2>&1 &
    disown
    echo "    started (PID $!), forwarding to localhost:8000/api/billing/webhook"
    echo "    logs: $STRIPE_LOG -- stop with: pkill -f 'stripe listen --forward-to'"
  fi
fi
