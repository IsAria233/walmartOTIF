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

Check: http://localhost:8080/health, then `/api/auth/health`, `/api/domain/health`, `/api/agent/health`.

## Working agreement

- `main` is protected; work on `feature/<JIRA-KEY>-short-name` branches and merge by pull request.
- Put the Jira key in PR titles, for example `OTIF-12 Add appointment history API`.
- Never commit `.env` or API keys.
