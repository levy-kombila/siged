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

from app.core.config import get_settings
from app.core.database import init_engine, initialize
from app.jobs import hot_folder, mail_ingest, tasks

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s : %(message)s")
logger = logging.getLogger("siged.worker")


def job_hot_folder():
    res = hot_folder.scan()
    if res["processed"] or res["errors"]:
        logger.info("Hot folder : %s capturé(s), %s erreur(s)", len(res["processed"]), len(res["errors"]))


def main():
    init_engine()
    initialize()
    sched = BlockingScheduler(timezone="Africa/Libreville")
    sched.add_job(job_hot_folder, "interval", minutes=1, id="hot_folder", max_instances=1)
    if get_settings().imap_host:
        sched.add_job(mail_ingest.poll, "interval", minutes=5, id="imap", max_instances=1)
    sched.add_job(tasks.retry_conversions, "cron", hour=1, minute=30, id="retry_conversions")
    sched.add_job(tasks.run_integrity, "cron", hour=2, minute=0, id="integrity")
    sched.add_job(tasks.run_retention, "cron", hour=3, minute=0, id="retention")
    logger.info("Worker SIGED démarré : %s", [j.id for j in sched.get_jobs()])
    sched.start()


if __name__ == "__main__":
    main()
