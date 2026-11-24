#!/usr/bin/env bash
# Writes .env for a server: new random secrets, and the hash of a demo password you choose.
# Nothing you type is shown or stored anywhere except .env (readable by you only).
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -e .env ]; then
  echo ".env already exists. Move it away first if you want a new one." >&2
  exit 1
fi

read -rsp "Password for the three demo accounts (12 characters or more): " demo_password; echo
if [ "${#demo_password}" -lt 12 ]; then
  echo "Too short: this page is reachable from the internet." >&2
  exit 1
fi
read -rsp "Anthropic API key: " anthropic_key; echo
read -rp "LangFuse public key (leave blank for no tracing): " langfuse_public
langfuse_secret=""
if [ -n "$langfuse_public" ]; then
  read -rsp "LangFuse secret key: " langfuse_secret; echo
fi

echo "Hashing the password..."
password_hash=$(printf '%s' "$demo_password" | docker run --rm -i python:3.12-slim sh -c \
  'pip install -q argon2-cffi >/dev/null 2>&1 && python -c "import sys; from argon2 import PasswordHasher; print(PasswordHasher().hash(sys.stdin.read()))"')
case "$password_hash" in
  '$argon2'*) ;;
  *) echo "Could not hash the password." >&2; exit 1 ;;
esac

umask 077
cat > .env <<EOF
POSTGRES_USER=otif
POSTGRES_PASSWORD=$(openssl rand -hex 24)
POSTGRES_DB=otif
JWT_SECRET=$(openssl rand -hex 32)
# Single quotes keep the dollar signs in the hash literal.
AUTH_DEMO_PASSWORD_HASH='${password_hash}'
ANTHROPIC_API_KEY=${anthropic_key}
LANGFUSE_PUBLIC_KEY=${langfuse_public}
LANGFUSE_SECRET_KEY=${langfuse_secret}
LANGFUSE_HOST=https://us.cloud.langfuse.com
EOF
echo ".env written."
