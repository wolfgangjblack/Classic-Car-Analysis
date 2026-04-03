"""Shared FastAPI dependencies (database sessions, settings, OpenAI client, etc.)."""

from functools import lru_cache

from openai import OpenAI
from sqlalchemy.orm import Session

from .config import get_settings
from .exceptions import CarAnalysisError
from .models.db import create_session_factory, get_engine


@lru_cache()
def get_openai_client() -> OpenAI:
    """Return a single, cached OpenAI client shared across the application."""
    settings = get_settings()
    if not settings.openai_api_key:
        raise CarAnalysisError("OPENAI_API_KEY environment variable not set")
    return OpenAI(api_key=settings.openai_api_key)


@lru_cache()
def _get_engine():
    """Lazily create and cache a single database engine."""
    settings = get_settings()
    return get_engine(settings.database_url)


def _get_session_factory():
    return create_session_factory(_get_engine())


def get_db():
    """FastAPI dependency that yields a database session."""
    SessionLocal = _get_session_factory()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_db_session() -> Session:
    """Get a database session for non-FastAPI contexts (background tasks, CLI)."""
    SessionLocal = _get_session_factory()
    session: Session = SessionLocal()
    return session
