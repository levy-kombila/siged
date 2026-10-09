"""Connexion à la base SQL (PostgreSQL en production, SQLite en développement)."""
import json
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


_engine = None
SessionLocal = sessionmaker(autoflush=False, expire_on_commit=False)


def init_engine(url: str | None = None):
    """(Ré)initialise le moteur SQLAlchemy. Appelé au démarrage et par les tests."""
    global _engine
    if _engine is not None:
        _engine.dispose()
    url = url or get_settings().database_url
    kwargs = {"pool_pre_ping": True,
              "json_serializer": lambda o: json.dumps(o, ensure_ascii=False, default=str)}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    elif get_settings().serverless:
        # Serverless : pas de pool local (chaque instance est éphémère) ; le pool est assuré
        # côté fournisseur (Neon -pooler / Supabase Supavisor, PgBouncer en mode transaction),
        # incompatible avec les requêtes préparées automatiques de psycopg 3.
        kwargs.update(poolclass=NullPool, connect_args={"prepare_threshold": None})
    else:
        kwargs.update(pool_size=10, max_overflow=20)
    _engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):
        @event.listens_for(_engine, "connect")
        def _fk_on(dbapi_conn, _):  # noqa: ANN001
            dbapi_conn.execute("PRAGMA foreign_keys=ON")
    SessionLocal.configure(bind=_engine)
    return _engine


def get_engine():
    return _engine or init_engine()


def is_postgres() -> bool:
    return get_engine().dialect.name == "postgresql"


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


STARTUP_LOCK_ID = 15489_14721  # identifiant arbitraire du verrou de démarrage


@contextmanager
def startup_lock():
    """Sérialise l'initialisation (création du schéma, données initiales) entre processus.

    L'API tourne avec plusieurs workers Uvicorn et le worker planifié démarre en même
    temps : sans verrou, ils créent les mêmes tables simultanément et l'un d'eux échoue
    (violation d'unicité dans le catalogue PostgreSQL). Le verrou consultatif de session
    est libéré à la sortie du bloc, ou automatiquement si le processus s'arrête.
    """
    engine = get_engine()
    if engine.dialect.name != "postgresql":
        yield
        return
    with engine.connect() as conn:
        conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": STARTUP_LOCK_ID})
        conn.commit()
        try:
            yield
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": STARTUP_LOCK_ID})
            conn.commit()


def create_schema():
    """Crée les tables puis applique les objets spécifiques PostgreSQL
    (index plein texte, triggers d'inaltérabilité du journal d'audit).
    À appeler à l'intérieur de startup_lock()."""
    from app import models  # noqa: F401  (enregistre les modèles)

    engine = get_engine()
    Base.metadata.create_all(engine)
    if engine.dialect.name == "postgresql":
        sql = (Path(__file__).resolve().parents[2] / "sql" / "postgres_init.sql").read_text()
        raw = engine.raw_connection()  # exécution directe (le SQL contient des '%' PL/pgSQL)
        try:
            with raw.cursor() as cur:
                cur.execute(sql)
            raw.commit()
        finally:
            raw.close()


def initialize():
    """Démarrage complet et sûr en multi-processus : schéma + rôles + admin + plan de classement."""
    from app.services.bootstrap import seed

    with startup_lock():
        create_schema()
        with SessionLocal() as db:
            seed(db)
