# Auth service

`POST /login` accepts a JSON object with `username` and `password`. The service
sets the JWT `sub` to the account's stable user UUID. Access tokens expire in 30 minutes.

| Demo account | Role | Password hash variable |
| --- | --- | --- |
| `demo_associate` | `dispute_associate` | `AUTH_DEMO_PASSWORD_HASH` |
| `demo_manager` | `compliance_manager` | `AUTH_DEMO_MANAGER_PASSWORD_HASH` |

## Run locally

From `auth-service/`, set a signing key and generate a hash from a demo password
entered at the prompt.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
export JWT_SECRET="$(python -c 'import secrets; print(secrets.token_hex(32))')"
export AUTH_DEMO_PASSWORD_HASH="$(python -c 'from argon2 import PasswordHasher; from getpass import getpass; print(PasswordHasher().hash(getpass("Demo password: ")))')"
export AUTH_DEMO_MANAGER_PASSWORD_HASH="$(python -c 'from argon2 import PasswordHasher; from getpass import getpass; print(PasswordHasher().hash(getpass("Manager demo password: ")))')"
python -m uvicorn app.main:app --port 8000
```

Open `http://127.0.0.1:8000/docs` and use `POST /login` with a configured demo account
and its password. A successful request returns `access_token` and
`token_type`. Invalid credentials return `401`.

Use the **Authorize** button in Swagger UI to enter the access token, then call
`GET /me`. It returns `user_id` and `role` after verifying the bearer token.
Requests with a missing, invalid, or expired token return `401`.

For Docker Compose, set `JWT_SECRET` and demo password hashes in the repository's
`.env` file. Put each hash in single quotes so Compose reads the dollar signs literally. The
gateway exposes `POST /api/auth/login` and `GET /api/auth/me`.
