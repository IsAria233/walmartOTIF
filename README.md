# Walmart OTIF Fine Dispute Investigation Agent

Sept Python GenAI group project. An internal tool for Walmart's OTIF dispute
associates: an agent investigates questionable OTIF fines one PO line at a time,
rules assign accountability, and a person approves. All data is generated or mocked.

Team: Kunze Wei, Ivo Zeng, Xiwen Huang

## Services

| Folder | What it is |
| --- | --- |
| `gateway/` | Nginx API gateway: `/api/auth`, `/api/domain`, `/api/agent` |
| `auth-service/` | FastAPI: login, JWT, roles |
| `domain-service/` | FastAPI + SQLAlchemy + PostgreSQL: mock systems, OTIF rules engine, cases, approvals |
| `agent-service/` | FastAPI + LangGraph + LangFuse: investigator agent, tools, guardrails |
| `frontend/` | React + React Router behind Nginx |
| `data-gen/` | Truth-first data generator and golden dataset |
| `eval/` | Golden dataset evaluation runner |
| `docs/` | Proposal and project plan |

## Run locally

    cp .env.example .env      # fill in secrets
    docker compose up --build

The gateway listens on `http://localhost:8080`. Check `/health`,
`/api/auth/health`, `/api/domain/health`, and `/api/agent/health`.

| Public gateway route | Target service route |
| --- | --- |
| `POST /api/auth/login` | Auth `POST /login` |
| `GET /api/auth/me` | Auth `GET /me` |
| `/api/domain/v1/...` | Domain `/api/v1/...` |
| `/api/agent/...` | Agent `/...` |

The frontend is at `http://localhost:3000`.

Send `Authorization: Bearer <token>` on every request except login and the
health checks. The gateway forwards the header. Every domain-service route
checks it; agent-service calls domain-service with its own short-lived token
(role `agent_service`), which can do case work and cannot approve.

A handed-off case is resolved by a person: `POST
/api/domain/v1/investigation-cases/{id}/manual-finding` with `cause_code` and
`rationale` (dispute associate or compliance manager). The cause is one of C1-C5
that applies to the fine type, or `OTHER` with an `accountable_party`. The rules engine then
computes the result and the normal approval follows. View gateway logs with `docker compose logs gateway`.

## End-to-end slice

One fine from login to approval through every service: auth login, the domain
work queue, the agent's investigation, the rules engine result, then approval.

    # .env needs JWT_SECRET, AUTH_DEMO_PASSWORD_HASH (hash of the demo password) and ANTHROPIC_API_KEY
    docker compose up -d --build
    docker compose run --rm -T -v "$PWD/data-gen:/data:ro" domain-service \
      python -m scripts.load_seed_cases /data/seed_cases/seed_cases.json
    uv run --with httpx python scripts/e2e_slice.py --fine FINE-1001 --gateway http://localhost:8080

A closed case cannot be investigated again. To start over, `docker compose down -v`
and repeat the steps above. Outside Docker, `scripts/reset_local_db.sh` wipes and
reloads the database named by `DATABASE_URL`.

### Agent API

All three calls need `Authorization: Bearer <token>` from any signed-in internal user.

| Call | What it does |
| --- | --- |
| `POST /api/agent/investigations` `{"case_id": ...}` | Investigates the case until it is handed off or waits for approval. With an `Idempotency-Key` header (a UUID), repeating the request returns the same run and continues it if an earlier attempt failed part-way. |
| `GET /api/agent/investigations/{run_id}` | The run: status, findings, tool log, LangFuse trace id. |
| `POST /api/agent/investigations/{run_id}/resume` | Call after an approval decision. The run reads the result and finishes (`approved` / `rejected`), or pauses again for the manager. |

Runs are checkpointed in Postgres (`AGENT_CHECKPOINT_DSN`, set in `docker-compose.yml`),
so they survive a restart. Without it they are kept in memory. A handoff is recorded
on the case with the agent's findings: `GET /api/domain/v1/investigation-cases/{id}`
returns it as `handoff`.

## Working agreement

- `main` is protected; work on `feature/<JIRA-KEY>-short-name` branches and merge by pull request.
- Put the Jira key in PR titles, for example `OTIF-12 Add appointment history API`.
- Never commit `.env` or API keys.
