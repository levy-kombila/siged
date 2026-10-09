"""Déclenchement HTTP des tâches planifiées (Vercel Cron Jobs ou tout planificateur externe).

Vercel envoie l'en-tête « Authorization: Bearer <CRON_SECRET> » ; sans secret configuré,
la route est désactivée.
"""
import hmac

from fastapi import APIRouter, Header, HTTPException

from app.core.config import get_settings
from app.jobs import tasks

router = APIRouter(prefix="/api/cron", tags=["Supervision"])


@router.get("/daily", summary="Tâches quotidiennes : conversions, messagerie, intégrité, DUA")
def daily(authorization: str = Header("")):
    secret = get_settings().cron_secret
    if not secret:
        raise HTTPException(404, "Tâches planifiées HTTP désactivées (CRON_SECRET absent)")
    if not hmac.compare_digest(authorization, f"Bearer {secret}"):
        raise HTTPException(401, "Secret invalide")
    return tasks.daily()
