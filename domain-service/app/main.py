"""Domain service: mock Walmart systems, OTIF rules engine, cases and approvals.

Mock systems exposed as read APIs: fine records (Retail Link scorecard),
disputes (HighRadius), POs with versions, ASNs, appointment history,
gate logs, receiving records, weather.
"""
from fastapi import FastAPI

app = FastAPI(title="domain-service")


@app.get("/health")
def health():
    return {"service": "domain-service", "status": "ok"}


# TODO: read APIs for each mock system (used by agent tools and frontend)
# TODO: rules engine: scope check, delivery window, cause -> accountability,
#       per-line fine (non-compliant cases x cost x 3%)
# TODO: pre-invoice scanner that flags projected fines
# TODO: investigation cases, line outcomes, approvals (role-checked)
