#!/usr/bin/env bash
# docker compose with the server settings applied. Run from anywhere:
#   deploy/compose.sh up -d --build
#   deploy/compose.sh logs -f agent-service
set -euo pipefail
cd "$(dirname "$0")/.."
exec docker compose -f docker-compose.yml -f deploy/docker-compose.ec2.yml "$@"
