"""SQLAlchemy engine/session management (sync, per docs/INTERFACES.md).

The engine is created lazily so tests can set ``DATABASE_URL`` before any DB
access. SQLite URLs get ``check_same_thread=False`` because request handlers
and background run tasks share the file across threads (each event-loop thread
serializes its own access, and SQLite in demo mode is single-writer anyway).
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.models import Base

logger = logging.getLogger("agentforge.db")

_engine: Optional[Engine] = None
_session_factory: Optional[sessionmaker[Session]] = None


def _ensure_sqlite_dir(database_url: str) -> None:
    """Create the parent directory of a file-based SQLite database if needed."""
    try:
        url = make_url(database_url)
        if url.get_backend_name() != "sqlite":
            return
        database = url.database
        if not database or database == ":memory:":
            return
        # "sqlite:///./agentforge.db" -> relative path; resolve against cwd.
        Path(database).parent.mkdir(parents=True, exist_ok=True)
    except Exception:  # pragma: no cover - defensive; never block startup
        logger.warning("Could not pre-create directory for database URL", exc_info=True)


def get_engine() -> Engine:
    """Return the process-wide engine, creating it on first use."""
    global _engine
    if _engine is None:
        database_url = get_settings().database_url
        _ensure_sqlite_dir(database_url)
        connect_args: dict = {}
        if database_url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        _engine = create_engine(
            database_url,
            connect_args=connect_args,
            pool_pre_ping=True,
            future=True,
        )
        logger.info("Database engine created for %s", _engine.url)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """Return the process-wide sessionmaker, creating it on first use."""
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            bind=get_engine(), autoflush=False, expire_on_commit=False, future=True
        )
    return _session_factory


@contextmanager
def session_scope() -> Iterator[Session]:
    """Context manager yielding a fresh session (closed on exit).

    Used by background services; request handlers use the ``get_db``
    dependency instead. Note: SQLAlchemy 2.1 removed the context-manager
    protocol from ``sessionmaker`` itself, hence this helper.
    """
    db = get_session_factory()()
    try:
        yield db
    finally:
        db.close()


def reset_engine() -> None:
    """Dispose the current engine/session factory (used by tests)."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


def dispose_engine() -> None:
    """Dispose the engine on application shutdown."""
    reset_engine()


def check_database() -> bool:
    """Cheap connectivity probe (used by /healthz extension points)."""
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:  # pragma: no cover - defensive
        logger.exception("Database connectivity check failed")
        return False


def init_db() -> None:
    """Create tables (dev/demo convenience; Alembic is the canonical path in
    production) and seed the template marketplace rows."""
    import app.models  # noqa: F401 - ensure all models are registered on Base

    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    _seed_templates()
    logger.info("Database schema ensured and templates seeded")


def _seed_templates() -> None:
    """Upsert the pinned marketplace templates from ``app.templates_data``."""
    from app import templates_data

    factory = get_session_factory()
    with factory() as db:
        for spec in templates_data.TEMPLATES:
            row = db.get(templates_data.TemplateModel, spec["id"])
            if row is None:
                row = templates_data.TemplateModel(id=spec["id"])
                db.add(row)
            row.name = spec["name"]
            row.description = spec["description"]
            row.tags_json = list(spec.get("tags", []))
            row.team_json = list(spec.get("team", []))
            row.planner_prompt = spec["planner_prompt"]
            row.sample_mission = spec["sample_mission"]
            row.expected_dag_json = list(spec.get("expected_dag", []))
            row.report_outline_json = list(spec.get("report_outline", []))
        db.commit()
    logger.info("Seeded %d templates", len(templates_data.TEMPLATES))
