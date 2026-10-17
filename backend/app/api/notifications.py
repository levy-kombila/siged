"""API Notifications et échéances d'obsolescence."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import Principal, require
from app.core.security import Perm
from app.models import Notification
from app.schemas import NotificationList, NotificationOut, ObsolescenceItem
from app.services import obsolescence

router = APIRouter(prefix="/api/notifications", tags=["Notifications"])
deadlines = APIRouter(prefix="/api/obsolescence", tags=["Notifications"])


@router.get("", response_model=NotificationList, summary="Mes notifications (les plus récentes d'abord)")
def my_notifications(unread_only: bool = False, size: int = Query(30, ge=1, le=200), db: Session = Depends(get_db),
                     p: Principal = Depends(require(Perm.DOC_READ))):
    if p.user_id is None:  # clé d'API : pas de boîte de notifications
        return {"unread": 0, "items": []}
    q = select(Notification).where(Notification.user_id == p.user_id)
    if unread_only:
        q = q.where(Notification.read_at.is_(None))
    items = db.execute(q.order_by(Notification.read_at.is_not(None), Notification.created_at.desc(),
                                  Notification.id.desc()).limit(size)).scalars().all()
    unread = db.execute(select(func.count(Notification.id)).where(
        Notification.user_id == p.user_id, Notification.read_at.is_(None))).scalar_one()
    return {"unread": unread, "items": items}


@router.post("/{notif_id}/read", response_model=NotificationOut, summary="Marquer comme lue")
def mark_read(notif_id: int, db: Session = Depends(get_db), p: Principal = Depends(require(Perm.DOC_READ))):
    n = db.get(Notification, notif_id)
    if not n or n.user_id != p.user_id:
        raise HTTPException(404, "Notification introuvable")
    n.read_at = n.read_at or datetime.now(timezone.utc)
    db.commit()
    return n


@router.post("/read-all", summary="Tout marquer comme lu")
def mark_all_read(db: Session = Depends(get_db), p: Principal = Depends(require(Perm.DOC_READ))):
    res = db.execute(update(Notification).where(Notification.user_id == p.user_id, Notification.read_at.is_(None))
                     .values(read_at=datetime.now(timezone.utc)))
    db.commit()
    return {"updated": res.rowcount or 0}


@router.post("/run", summary="Générer maintenant les alertes d'obsolescence (sinon chaque matin)")
def run(db: Session = Depends(get_db), p: Principal = Depends(require(Perm.ADMIN_JOBS))):
    return obsolescence.run_alerts(db, p.actor)


@deadlines.get("/upcoming", response_model=list[ObsolescenceItem],
               summary="Échéances à venir : fin de validité et fin de DUA (échues incluses)")
def upcoming(days: int = Query(90, ge=0, le=3650), db: Session = Depends(get_db),
             _: Principal = Depends(require(Perm.DOC_READ))):
    return obsolescence.upcoming(db, days)
