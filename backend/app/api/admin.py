"""API d'administration : journal d'audit, intégrité, DUA / sort final, statistiques, intégrations."""
import secrets
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import Principal, require
from app.core.security import Perm, generate_api_key
from app.models import ApiKey, AuditLog, Document, DocumentVersion, IntegrityCheck, Role, Webhook
from app.schemas import (ApiKeyCreated, ApiKeyIn, ApiKeyOut, AuditOut, DocumentOut, RetentionRunIn,
                         WebhookCreated, WebhookIn, WebhookOut)
from app.services import audit, events, integrity, retention

router = APIRouter(prefix="/api", tags=["Administration & conformité"])


# ------------------------------------------------------------------ Audit
@router.get("/audit", response_model=list[AuditOut], summary="Consulter le journal d'audit")
def audit_list(action: str | None = None, actor: str | None = None, object_id: str | None = None,
               date_from: datetime | None = None, date_to: datetime | None = None,
               page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=500),
               db: Session = Depends(get_db), _: Principal = Depends(require(Perm.AUDIT_READ))):
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if actor:
        stmt = stmt.where(AuditLog.actor == actor)
    if object_id:
        stmt = stmt.where(AuditLog.object_id == object_id)
    if date_from:
        stmt = stmt.where(AuditLog.created_at >= date_from)
    if date_to:
        stmt = stmt.where(AuditLog.created_at <= date_to)
    return db.execute(stmt.order_by(AuditLog.id.desc()).offset((page - 1) * size).limit(size)).scalars().all()


@router.get("/audit/verify", summary="Vérifier l'inaltérabilité de la chaîne d'audit")
def audit_verify(db: Session = Depends(get_db), p: Principal = Depends(require(Perm.AUDIT_READ))):
    result = audit.verify_chain(db)
    audit.log(db, p.actor, "AUDIT_VERIFY", "audit", None, {"valid": result["valid"]})
    return result


# ------------------------------------------------------------------ Intégrité
@router.post("/admin/integrity/run", summary="Lancer un contrôle d'intégrité complet (SHA-256)")
def integrity_run(db: Session = Depends(get_db), p: Principal = Depends(require(Perm.ADMIN_JOBS))):
    c = integrity.run_check(db, p.actor)
    return {"id": c.id, "files_checked": c.files_checked, "failures": c.failures,
            "started_at": c.started_at, "finished_at": c.finished_at}


@router.get("/admin/integrity/last")
def integrity_last(db: Session = Depends(get_db), _: Principal = Depends(require(Perm.AUDIT_READ))):
    c = db.execute(select(IntegrityCheck).order_by(IntegrityCheck.id.desc()).limit(1)).scalar()
    if not c:
        return None
    return {"id": c.id, "files_checked": c.files_checked, "failures": c.failures,
            "started_at": c.started_at, "finished_at": c.finished_at}


# ------------------------------------------------------------------ DUA / sort final
@router.get("/retention/due", response_model=list[DocumentOut], summary="Documents dont la DUA est échue")
def retention_due(db: Session = Depends(get_db), _: Principal = Depends(require(Perm.RETENTION_MANAGE))):
    return retention.due_documents(db)


@router.get("/retention/upcoming", response_model=list[DocumentOut], summary="Échéances DUA à venir")
def retention_upcoming(days: int = Query(90, ge=1, le=3650), db: Session = Depends(get_db),
                       _: Principal = Depends(require(Perm.RETENTION_MANAGE))):
    return retention.upcoming(db, date.today() + timedelta(days=days))


@router.post("/retention/run", summary="Appliquer le sort final (dry_run=true : bordereau seulement)")
def retention_run(data: RetentionRunIn, db: Session = Depends(get_db),
                  p: Principal = Depends(require(Perm.RETENTION_MANAGE))):
    return retention.run(db, p.actor, data.document_ids, data.dry_run)


# ------------------------------------------------------------------ Tableau de bord
@router.get("/admin/stats", summary="Indicateurs du tableau de bord")
def stats(db: Session = Depends(get_db), _: Principal = Depends(require(Perm.DOC_READ))):
    by_status = dict(db.execute(select(Document.status, func.count()).group_by(Document.status)).all())
    volume = db.execute(select(func.count(DocumentVersion.id), func.coalesce(func.sum(DocumentVersion.size_bytes), 0))).one()
    conv = dict(db.execute(select(DocumentVersion.conversion_status, func.count())
                           .group_by(DocumentVersion.conversion_status)).all())
    return {"documents_by_status": by_status, "versions": volume[0], "bytes": int(volume[1]),
            "conversion": conv, "retention_due": len(retention.due_documents(db))}


# ------------------------------------------------------------------ Intégrations : clés d'API
integrations = APIRouter(prefix="/api/integrations", tags=["Interopérabilité"])


@integrations.get("/events")
def list_events(_: Principal = Depends(require(Perm.INTEGRATION_MANAGE))):
    return events.EVENTS


@integrations.get("/api-keys", response_model=list[ApiKeyOut])
def list_keys(db: Session = Depends(get_db), _: Principal = Depends(require(Perm.INTEGRATION_MANAGE))):
    return db.execute(select(ApiKey).order_by(ApiKey.id)).scalars().all()


@integrations.post("/api-keys", response_model=ApiKeyCreated, status_code=201,
                   summary="Créer une clé d'API pour une application tierce (ERP, SIRH...)")
def create_key(data: ApiKeyIn, db: Session = Depends(get_db), p: Principal = Depends(require(Perm.INTEGRATION_MANAGE))):
    role = db.execute(select(Role).where(Role.name == data.role)).scalar()
    if not role or role.name == "admin":
        raise HTTPException(422, "Rôle invalide pour une clé d'API (admin interdit)")
    if db.execute(select(ApiKey).where(ApiKey.name == data.name)).first():
        raise HTTPException(409, "Nom déjà utilisé")
    raw, prefix, digest = generate_api_key()
    key = ApiKey(name=data.name, key_prefix=prefix, key_hash=digest, role_id=role.id)
    db.add(key)
    db.flush()
    audit.log(db, p.actor, "API_KEY_CREATE", "api_key", str(key.id), {"name": data.name, "role": data.role})
    db.refresh(key)
    return ApiKeyCreated(**ApiKeyOut.model_validate(key).model_dump(), api_key=raw)


@integrations.delete("/api-keys/{key_id}", status_code=204)
def revoke_key(key_id: int, db: Session = Depends(get_db), p: Principal = Depends(require(Perm.INTEGRATION_MANAGE))):
    key = db.get(ApiKey, key_id)
    if not key:
        raise HTTPException(404, "Clé introuvable")
    key.is_active = False
    audit.log(db, p.actor, "API_KEY_REVOKE", "api_key", str(key.id), {"name": key.name})


@integrations.get("/webhooks", response_model=list[WebhookOut])
def list_webhooks(db: Session = Depends(get_db), _: Principal = Depends(require(Perm.INTEGRATION_MANAGE))):
    return db.execute(select(Webhook).order_by(Webhook.id)).scalars().all()


@integrations.post("/webhooks", response_model=WebhookCreated, status_code=201,
                   summary="Abonner une application aux événements (signature HMAC-SHA256)")
def create_webhook(data: WebhookIn, db: Session = Depends(get_db),
                   p: Principal = Depends(require(Perm.INTEGRATION_MANAGE))):
    unknown = [e for e in data.events if e != "*" and e not in events.EVENTS]
    if unknown:
        raise HTTPException(422, f"Événements inconnus : {unknown}")
    hook = Webhook(name=data.name, url=data.url, events=data.events, secret=secrets.token_hex(24))
    db.add(hook)
    db.flush()
    audit.log(db, p.actor, "WEBHOOK_CREATE", "webhook", str(hook.id), {"url": data.url, "events": data.events})
    db.refresh(hook)
    return WebhookCreated(**WebhookOut.model_validate(hook).model_dump(), secret=hook.secret)


@integrations.delete("/webhooks/{hook_id}", status_code=204)
def delete_webhook(hook_id: int, db: Session = Depends(get_db), p: Principal = Depends(require(Perm.INTEGRATION_MANAGE))):
    hook = db.get(Webhook, hook_id)
    if not hook:
        raise HTTPException(404, "Webhook introuvable")
    hook.is_active = False
    audit.log(db, p.actor, "WEBHOOK_DISABLE", "webhook", str(hook.id), {"url": hook.url})
