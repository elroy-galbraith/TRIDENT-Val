import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Postgres in docker-compose; falls back to local SQLite for zero-config dev.
# SQLite path is anchored to the repo root so it works regardless of cwd.
_REPO_ROOT = Path(__file__).resolve().parents[2]
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{_REPO_ROOT / 'trident.db'}")

# Some managed Postgres providers hand out a bare postgres(ql):// connection string
# with no driver marker; psycopg2 is what's installed, so pin it explicitly.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg2://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
