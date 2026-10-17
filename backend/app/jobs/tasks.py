"""Tâches de maintenance, sans dépendance à l'ordonnanceur.

Appelées par le worker APScheduler (déploiement Docker) ou par une requête HTTP
planifiée (Vercel Cron, GitHub Actions...) via GET /api/cron/daily.
"""
import logging

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models import ConversionStatus, DocumentVersion
from app.services import integrity, obsolescence, retention
from app.services.audit import Actor
from app.services.documents import process_version

logger = logging.getLogger("siged.tasks")
WORKER = Actor(None, "system:worker")


def run_integrity() -> dict:
    with SessionLocal() as db:
        c = integrity.run_check(db, WORKER)
        logger.info("Intégrité : %s fichiers, %s anomalie(s)", c.files_checked, len(c.failures))
        return {"files_checked": c.files_checked, "failures": len(c.failures)}


def run_retention() -> dict:
    with SessionLocal() as db:
        rep = retention.run(db, WORKER, dry_run=not get_settings().retention_auto_execute)
        logger.info("DUA : %s à éliminer, %s à verser (dry_run=%s)",
                    len(rep["destroyed"]), len(rep["archived"]), rep["dry_run"])
        return {"dry_run": rep["dry_run"], "destroy": len(rep["destroyed"]),
                "archive": len(rep["archived"]), "errors": len(rep["errors"])}


def run_obsolescence() -> dict:
    with SessionLocal() as db:
        return obsolescence.run_alerts(db, WORKER)


def retry_conversions(limit: int = 50) -> dict:
    with SessionLocal() as db:
        ids = db.execute(select(DocumentVersion.id).where(
            DocumentVersion.conversion_status.in_([ConversionStatus.PENDING, ConversionStatus.FAILED]),
            DocumentVersion.storage_key.is_not(None)).limit(limit)).scalars().all()
    for vid in ids:
        process_version(vid)
    return {"reprocessed": len(ids)}


def run_mail() -> dict:
    if not get_settings().imap_host:
        return {"skipped": True}
    from app.jobs import mail_ingest
    return {"documents": mail_ingest.poll()}


def daily() -> dict:
    """Enchaînement quotidien ; chaque étape est isolée pour qu'un échec n'empêche pas les autres."""
    report = {}
    for name, fn in (("conversions", retry_conversions), ("mail", run_mail),
                     ("integrity", run_integrity), ("retention", run_retention), ("obsolescence", run_obsolescence)):
        try:
            report[name] = fn()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Tâche %s en échec", name)
            report[name] = {"error": str(exc)[:300]}
    return report
