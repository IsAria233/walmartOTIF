# Deploying to one EC2 instance

The same `docker compose` stack as on a laptop, on one Ubuntu instance, with
server settings from `docker-compose.ec2.yml`: only the frontend is published
(port 80), containers restart on reboot, and logs are size-limited.

All data is generated, but the page is on the internet and each investigation
calls the model, so the steps below use new secrets and a new demo password.

## 1. Create the instance (AWS console)

| Setting | Value |
| --- | --- |
| Image | Ubuntu Server 24.04 LTS |
| Type | `t3.medium` (4 GB). Smaller types run out of memory building the frontend. |
| Storage | 30 GB |
| Security group, inbound | SSH (22) from your IP only; HTTP (80) from anywhere |

Do not open 8080, 5432 or any other port. To keep the address across stops,
attach an Elastic IP.

## 2. Set up the host (once)

    ssh ubuntu@<public-ip>
    git clone https://github.com/IsAria233/walmartOTIF.git
    cd walmartOTIF
    deploy/setup-host.sh
    exit                      # log in again so docker works without sudo

## 3. Create `.env` on the server (once)

    ssh ubuntu@<public-ip>
    cd walmartOTIF
    deploy/make-env.sh

It asks for a demo password (12 characters or more), the Anthropic API key and,
optionally, the LangFuse keys. It generates the JWT secret and the database
password. Do not reuse the laptop `.env` or the old demo password, and never
copy `.env` into the repository.

Set a spending limit on the Anthropic key in the Anthropic console: anyone with
the demo password can start investigations.

## 4. Start and load data

    deploy/compose.sh up -d --build
    deploy/compose.sh run --rm -T -v "$PWD/data-gen:/data:ro" domain-service \
      python -m scripts.load_seed_cases /data/seed_cases/seed_cases.json
    deploy/compose.sh run --rm -T -v "$PWD/data-gen:/data:ro" domain-service \
      python -m scripts.load_seed_cases /data/dataset/cases.json

Open `http://<public-ip>/` and sign in as `demo_associate`, `demo_manager` or
`demo_admin` with the password from step 3.

## Day to day

| Task | Command |
| --- | --- |
| Is everything up? | `deploy/compose.sh ps` |
| Logs of one service | `deploy/compose.sh logs --tail 200 -f agent-service` |
| Deploy a new version | `git pull && deploy/compose.sh up -d --build` |
| Reset to fresh cases before a demo | `deploy/compose.sh down -v`, then step 4 again |
| Stop without losing data | `deploy/compose.sh stop` (or stop the instance) |

Migrations run when domain-service starts. Traces are in LangFuse when its keys
are set.

## Known limits

- Plain HTTP: the password and tokens are not encrypted in transit. Acceptable
  for a short demo with generated data. HTTPS needs a domain name and a proxy
  that obtains a certificate.
- One instance holds everything, including Postgres. Terminating the instance
  or `down -v` deletes the data, which can be reloaded from `data-gen/`.
- Without an Elastic IP the address changes when the instance is stopped.
