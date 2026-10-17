"""Alertes d'obsolescence : prévenir AVANT qu'un document ne devienne obsolète.

Deux échéances sont surveillées pour chaque document actif (brouillon, en validation, validé) :
  * VALIDITY  : date de fin de validité (valid_until) -> le document devient obsolète
                (contrat expiré, attestation périmée, agrément à renouveler...) ;
  * RETENTION : fin de la DUA (retention_until) -> le sort final doit être appliqué
                (ignorée pendant un gel juridique).

Paliers configurables (SIGED_OBSOLESCENCE_ALERT_DAYS, défaut « 90,30,7,0 ») : une notification
par document, type et palier atteint, adressée au déposant et aux profils « retention:manage ».
Le job est idempotent : relancé le même jour, il ne crée aucun doublon.
"""
import logging
from datetime import date, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import Perm
from app.models import DocStatus, Document, Notification, NotificationKind, Role, User
from app.services import audit, events
from app.services.audit import Actor

logger = logging.getLogger("siged.obsolescence")
ACTIVE = [DocStatus.DRAFT, DocStatus.PENDING, DocStatus.VALIDATED]
LABELS = {NotificationKind.VALIDITY: "devient obsolète (fin de validité)",
          NotificationKind.RETENTION: "atteint la fin de sa DUA"}


def thresholds() -> list[int]:
    raw = get_settings().obsolescence_alert_days
    days = sorted({int(x) for x in raw.replace(";", ",").split(",") if x.strip().lstrip("-").isdigit() and int(x) >= 0})
    return days or [0]


def stage_for(days_left: int, steps: list[int]) -> str | None:
    """Palier atteint : le plus petit seuil >= jours restants (J-30 si 20 jours restent)."""
    if days_left <= 0:
        return "ECHU"
    for t in steps:
        if t > 0 and days_left <= t:
            return f"J-{t}"
    return None


def deadlines(doc: Document) -> list[tuple[str, date]]:
    out = []
    if doc.valid_until:
        out.append((NotificationKind.VALIDITY, doc.valid_until))
    if not doc.legal_hold:
        out.append((NotificationKind.RETENTION, doc.retention_until))
    return out


def upcoming(db: Session, days: int, today: date | None = None) -> list[dict]:
    """Échéances (validité et DUA) des documents actifs dans les `days` prochains jours, échues incluses."""
    today = today or date.today()
    limit = today + timedelta(days=days)
    docs = db.execute(select(Document).where(
        Document.status.in_(ACTIVE),
        or_(Document.valid_until <= limit, Document.retention_until <= limit),
    )).unique().scalars().all()
    items = [{"kind": kind, "due_date": due, "days_left": (due - today).days, "document": d}
             for d in docs for kind, due in deadlines(d) if due <= limit]
    return sorted(items, key=lambda x: (x["due_date"], x["kind"]))


def _recipients(db: Session, doc: Document) -> list[User]:
    managers = [u for u in db.execute(select(User).join(Role).where(User.is_active.is_(True))).unique().scalars()
                if Perm.RETENTION_MANAGE in (u.role.permissions or [])]
    users = {u.id: u for u in managers}
    if doc.creator and doc.creator.is_active:
        users[doc.creator.id] = doc.creator
    return list(users.values())


def run_alerts(db: Session, actor: Actor, today: date | None = None) -> dict:
    today = today or date.today()
    steps = thresholds()
    created: list[Notification] = []
    for item in upcoming(db, max(steps), today):
        doc, kind, due = item["document"], item["kind"], item["due_date"]
        stage = stage_for(item["days_left"], steps)
        if not stage:
            continue
        when = "aujourd'hui ou avant" if stage == "ECHU" else f"dans {item['days_left']} j"
        title = f"{doc.reference} {LABELS[kind]} — {'échu' if stage == 'ECHU' else stage}"
        message = (f"« {doc.title} » {LABELS[kind]} le {due.strftime('%d/%m/%Y')} ({when}).")
        for user in _recipients(db, doc):
            exists = db.execute(select(Notification.id).where(
                Notification.user_id == user.id, Notification.document_id == doc.id,
                Notification.kind == kind, Notification.stage == stage)).first()
            if exists:
                continue
            n = Notification(user_id=user.id, document_id=doc.id, kind=kind, stage=stage,
                             due_date=due, title=title, message=message)
            db.add(n)
            created.append(n)
    db.flush()
    by_user: dict[int, list[Notification]] = {}
    for n in created:
        by_user.setdefault(n.user_id, []).append(n)
    if created:
        audit.log(db, actor, "OBSOLESCENCE_ALERTS", "notification", None,
                  {"created": len(created), "users": len(by_user), "date": today.isoformat()}, commit=False)
    db.commit()
    for uid, notes in by_user.items():  # un e-mail récapitulatif par destinataire (si SMTP configuré)
        user = db.get(User, uid)
        if user and user.email:
            events.send_email([user.email], f"[GEDarchive] {len(notes)} échéance(s) de documents",
                              "\n".join(f"- {n.message}" for n in notes))
    logger.info("Obsolescence : %s notification(s) créée(s)", len(created))
    return {"created": len(created), "users": len(by_user)}
