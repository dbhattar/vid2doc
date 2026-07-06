from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .config import settings

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_session() -> Session:
    """Callers are responsible for closing (and committing, if writing) the
    returned session -- mirrors the connection-per-call pattern this module
    used before the Postgres/SQLAlchemy migration, to minimize churn in
    app/jobs.py's call sites."""
    return SessionLocal()
