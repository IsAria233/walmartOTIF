#!/usr/bin/env bash
# Wipe the local development database, re-run migrations and reload the seed cases.
# Needs DATABASE_URL (see README). Never point this at a database you want to keep.
set -euo pipefail
cd "$(dirname "$0")/../domain-service"
: "${DATABASE_URL:?Set DATABASE_URL first}"
uv run python - <<'PY'
import os
from sqlalchemy import create_engine, text
with create_engine(os.environ["DATABASE_URL"]).begin() as conn:
    conn.execute(text("DROP SCHEMA public CASCADE"))
    conn.execute(text("CREATE SCHEMA public"))
PY
uv run alembic upgrade head 2>&1 | tail -1
uv run python -m scripts.load_seed_cases ../data-gen/seed_cases/seed_cases.json
