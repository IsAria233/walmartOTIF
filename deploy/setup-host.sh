#!/usr/bin/env bash
# One-time setup of a fresh Ubuntu EC2 instance: installs Docker with the compose plugin.
set -euo pipefail
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sudo sh
fi
sudo usermod -aG docker "$USER"
docker --version
sudo docker compose version
echo "Docker is installed. Log out and back in so '$USER' can run docker without sudo."
