# Auth service

`POST /login` accepts a JSON object with `username` and `password`. The demo
username is `demo_associate`. Its stable user UUID is the JWT `sub`, and its
`dispute_associate` role is set by the service. Access tokens expire in 30 minutes.

## Run locally

From `auth-service/`, set a signing key and generate a hash from a demo password
entered at the prompt.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
export JWT_SECRET="$(python -c 'import secrets; print(secrets.token_hex(32))')"
export AUTH_DEMO_PASSWORD_HASH="$(python -c 'from argon2 import PasswordHasher; from getpass import getpass; print(PasswordHasher().hash(getpass("Demo password: ")))')"
python -m uvicorn app.main:app --port 8000
```

Open `http://127.0.0.1:8000/docs` and use `POST /login` with `demo_associate` and
the password you entered. A successful request returns `access_token` and
`token_type`. Invalid credentials return `401`.

Use the **Authorize** button in Swagger UI to enter the access token, then call
`GET /me`. It returns `user_id` and `role` after verifying the bearer token.
Requests with a missing, invalid, or expired token return `401`.

For Docker Compose, set both variables in the repository's `.env` file. Put the
Argon2 hash in single quotes so Compose reads the dollar signs literally. The
gateway exposes `POST /api/auth/login` and `GET /api/auth/me`.
