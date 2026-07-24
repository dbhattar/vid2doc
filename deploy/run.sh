#!/usr/bin/env bash
# Wrapper around `fab` that reads connection details from environment
# variables instead of retyping -H/-i on every invocation.
#
# Required: VPS_IP
# Optional: SSH_USER (default: deploy -- override to root only for the
#           one-time create-deploy-user task), SSH_KEY (default:
#           ~/.ssh/framewrite_vps)
#
# Usage:
#   VPS_IP=1.2.3.4 SSH_USER=root ./run.sh create-deploy-user
#   VPS_IP=1.2.3.4 ./run.sh bootstrap
#   VPS_IP=1.2.3.4 ./run.sh setup-tls
#   VPS_IP=1.2.3.4 ./run.sh deploy
#   VPS_IP=1.2.3.4 ./run.sh logs --service=worker --lines=200
#
# Export VPS_IP once per shell session to skip repeating it:
#   export VPS_IP=1.2.3.4
#   ./run.sh deploy

set -euo pipefail

if [[ -z "${VPS_IP:-}" ]]; then
  echo "ERROR: VPS_IP environment variable is not set." >&2
  echo "Usage: VPS_IP=<ip> [SSH_USER=deploy] [SSH_KEY=~/.ssh/framewrite_vps] $0 <fab-task> [fab-args...]" >&2
  exit 1
fi

if [[ $# -eq 0 ]]; then
  echo "ERROR: no fab task given." >&2
  echo "Usage: VPS_IP=<ip> [SSH_USER=deploy] [SSH_KEY=~/.ssh/framewrite_vps] $0 <fab-task> [fab-args...]" >&2
  exit 1
fi

SSH_USER="${SSH_USER:-deploy}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/framewrite_vps}"

cd "$(dirname "$0")"
exec fab -H "${SSH_USER}@${VPS_IP}" -i "${SSH_KEY}" "$@"
