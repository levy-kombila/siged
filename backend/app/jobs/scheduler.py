"""Ordonnanceur des tâches de fond (processus « worker » séparé de l'API).

    python -m app.jobs.scheduler

  * toutes les minutes  : capture du dossier partagé (hot folder)
  * toutes les 5 minutes: capture de la messagerie (si IMAP configuré)
  * 01:30 chaque nuit   : reprise des conversions PDF/A en échec ou en attente
  * 02:00 chaque nuit   : contrôle d'intégrité SHA-256 de tous les fichiers
  * 03:00 chaque nuit   : DUA -> bordereau d'élimination / versement (exécution si auto)
"""
import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import SessionLocal, create_schema, init_engine
from app.jobs import hot_folder, mail_ingest
from app.models import ConversionStatus, DocumentVersion
from app.services import integrity, retention
from app.services.audit import Actor
from app.services.bootstrap import seed
from app.services.documents import process_version

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s : %(message)s")
logger = logging.getLogger("siged.worker")
WORKER = Actor(None, "system:worker")


def job_integrity():
    with SessionLocal() as db:
        c = integrity.run_check(db, WORKER)
        logger.info("Intégrité : %s fichiers, %s anomalie(s)", c.files_checked, len(c.failures))


def job_retention():
    with SessionLocal() as db:
        rep = retention.run(db, WORKER, dry_run=not get_settings().retention_auto_execute)
        logger.info("DUA : %s à éliminer, %s à verser (dry_run=%s)",
                    len(rep["destroyed"]), len(rep["archived"]), rep["dry_run"])


def job_retry_conversions():
    with SessionLocal() as db:
        ids = db.execute(select(DocumentVersion.id).where(DocumentVersion.conversion_status.in_(
            [ConversionStatus.PENDING, ConversionStatus.FAILED]), DocumentVersion.storage_key.is_not(None))).scalars().all()
    for vid in ids:
        process_version(vid)


def job_hot_folder():
    res = hot_folder.scan()
    if res["processed"] or res["errors"]:
        logger.info("Hot folder : %s capturé(s), %s erreur(s)", len(res["processed"]), len(res["errors"]))


def main():
    init_engine()
    create_schema()
    with SessionLocal() as db:
        seed(db)
    sched = BlockingScheduler(timezone="Africa/Libreville")
    sched.add_job(job_hot_folder, "interval", minutes=1, id="hot_folder", max_instances=1)
    if get_settings().imap_host:
        sched.add_job(mail_ingest.poll, "interval", minutes=5, id="imap", max_instances=1)
    sched.add_job(job_retry_conversions, "cron", hour=1, minute=30, id="retry_conversions")
    sched.add_job(job_integrity, "cron", hour=2, minute=0, id="integrity")
    sched.add_job(job_retention, "cron", hour=3, minute=0, id="retention")
    logger.info("Worker SIGED démarré : %s", [j.id for j in sched.get_jobs()])
    sched.start()


if __name__ == "__main__":
    main()
