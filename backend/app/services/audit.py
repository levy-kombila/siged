"""Journal d'audit inaltérable (ISO 15489 / OAIS) : ajout seul + chaînage SHA-256.

entry_hash = SHA256(prev_hash | horodatage | acteur | action | objet | détails canoniques)
Toute modification d'une ligne casse la chaîne et est détectée par verify_chain().
"""
import hashlib
import json
import threading
from datetime import datetime, timezone

from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from app.models import AuditLog

GENESIS = "0" * 64

# Sérialisation de l'écriture de la chaîne :
#  * PostgreSQL : verrou consultatif transactionnel (pg_advisory_xact_lock), valable entre processus ;
#  * SQLite (dev) : verrou de processus conservé jusqu'à la fin de la transaction de la session.
_chain_lock = threading.Lock()
_LOCK_FLAG = "siged_audit_lock"


@event.listens_for(Session, "after_transaction_end")
def _release(session: Session, transaction) -> None:
    # fin de la transaction de premier niveau : commit, rollback ou fermeture de session
    if transaction.parent is None and session.info.pop(_LOCK_FLAG, False):
        _chain_lock.release()


def _acquire(db: Session) -> None:
    if db.get_bind().dialect.name == "postgresql":
        db.execute(select(func.pg_advisory_xact_lock(15489)))
    elif not db.info.get(_LOCK_FLAG):
        _chain_lock.acquire()
        db.info[_LOCK_FLAG] = True


class Actor:
    """Identité de l'auteur d'une action (utilisateur, clé d'API ou système)."""

    def __init__(self, user_id: int | None = None, name: str = "system", ip: str = "", user_agent: str = ""):
        self.user_id, self.name, self.ip, self.user_agent = user_id, name, ip, user_agent


SYSTEM = Actor()


def _compute_hash(prev_hash: str, created_at: datetime, user_id, actor: str, action: str,
                  object_type: str, object_id, details: dict) -> str:
    payload = json.dumps({
        "prev": prev_hash, "ts": created_at.astimezone(timezone.utc).isoformat(timespec="microseconds"),
        "uid": user_id, "actor": actor, "action": action, "otype": object_type,
        "oid": object_id, "details": details,
    }, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def log(db: Session, actor: Actor, action: str, object_type: str = "", object_id: str | None = None,
        details: dict | None = None, commit: bool = True) -> AuditLog:
    details = json.loads(json.dumps(details or {}, default=str))
    _acquire(db)
    last = db.execute(select(AuditLog.entry_hash).order_by(AuditLog.id.desc()).limit(1)).scalar()
    prev = last or GENESIS
    now = datetime.now(timezone.utc)
    entry = AuditLog(
        created_at=now, user_id=actor.user_id, actor=actor.name, action=action,
        object_type=object_type, object_id=str(object_id) if object_id else None,
        ip_address=actor.ip[:45], user_agent=actor.user_agent[:500], details=details, prev_hash=prev,
        entry_hash=_compute_hash(prev, now, actor.user_id, actor.name, action, object_type,
                                 str(object_id) if object_id else None, details),
    )
    db.add(entry)
    if commit:
        db.commit()
    else:
        db.flush()
    return entry


def verify_chain(db: Session) -> dict:
    """Recalcule toute la chaîne ; retourne la première rupture éventuelle."""
    prev = GENESIS
    count = 0
    for e in db.execute(select(AuditLog).order_by(AuditLog.id)).scalars().yield_per(1000):
        created = e.created_at if e.created_at.tzinfo else e.created_at.replace(tzinfo=timezone.utc)
        expected = _compute_hash(prev, created, e.user_id, e.actor, e.action, e.object_type,
                                 e.object_id, e.details)
        if e.prev_hash != prev or e.entry_hash != expected:
            return {"valid": False, "entries_checked": count, "broken_at_id": e.id,
                    "message": f"Chaîne d'audit rompue à l'entrée #{e.id} (altération détectée)"}
        prev = e.entry_hash
        count += 1
    return {"valid": True, "entries_checked": count, "broken_at_id": None,
            "message": "Chaîne d'audit intègre"}
