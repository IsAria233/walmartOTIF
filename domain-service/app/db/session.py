"""Database engine and request-scoped session configuration."""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL must be configured")
    return url


engine = create_engine(database_url(), pool_pre_ping=True) if os.getenv("DATABASE_URL") else None
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False) if engine else None


def get_db():
    """FastAPI dependency yielding a session and always closing it."""
    if SessionLocal is None:
        raise RuntimeError("DATABASE_URL must be configured before opening a database session")
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
