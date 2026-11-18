"""Domain Service APIs and business workflow boundary."""
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from sqlalchemy.exc import IntegrityError

from app.api.routers import router
from app.services.exceptions import Conflict, DomainError, IntegrityViolation, InvalidRequest, NotFound, PolicyUnavailable

app = FastAPI(title="domain-service")
app.include_router(router)


@app.get("/health")
def health():
    return {"service": "domain-service", "status": "ok"}


@app.exception_handler(NotFound)
def not_found_handler(request: Request, exc: NotFound):
    return JSONResponse(status_code=404, content={"error": {"code": "not_found", "message": str(exc)}})


@app.exception_handler(Conflict)
def conflict_handler(request: Request, exc: Conflict):
    return JSONResponse(status_code=409, content={"error": {"code": "conflict", "message": str(exc)}})


@app.exception_handler(InvalidRequest)
@app.exception_handler(IntegrityViolation)
def invalid_handler(request: Request, exc: Exception):
    return JSONResponse(status_code=422, content={"error": {"code": "invalid_request", "message": str(exc)}})


@app.exception_handler(PolicyUnavailable)
def policy_handler(request: Request, exc: PolicyUnavailable):
    return JSONResponse(status_code=409, content={"error": {"code": "policy_unavailable", "message": str(exc)}})


@app.exception_handler(IntegrityError)
def database_integrity_handler(request: Request, exc: IntegrityError):
    return JSONResponse(status_code=409, content={"error": {"code": "integrity_conflict", "message": "The request conflicts with stored domain data"}})


@app.exception_handler(RequestValidationError)
def request_validation_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content=jsonable_encoder({"error": {"code": "validation_error", "message": "Request data is invalid", "details": exc.errors()}}))


@app.exception_handler(HTTPException)
def http_error_handler(request: Request, exc: HTTPException):
    detail = exc.detail
    if not (isinstance(detail, dict) and "error" in detail):
        detail = {"error": {"code": "http_error", "message": str(detail)}}
    return JSONResponse(status_code=exc.status_code, content=jsonable_encoder(detail), headers=exc.headers)
