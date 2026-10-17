"""Circuit de validation : machine à états stricte.

    DRAFT --submit--> PENDING_VALIDATION --approve--> VALIDATED (version figée)
                             |
                             +--reject (motif obligatoire)--> DRAFT

Règle de séparation des tâches : l'auteur d'un document ne peut pas le valider lui-même
(sauf administrateur).
"""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import Perm
from app.models import DocStatus, Document, Role, User, WorkflowEvent
from app.services import audit, events
from app.services.documents import BusinessError

TRANSITIONS = {
    "submit": (DocStatus.DRAFT, DocStatus.PENDING, Perm.DOC_WRITE, "document.submitted"),
    "approve": (DocStatus.PENDING, DocStatus.VALIDATED, Perm.DOC_VALIDATE, "document.validated"),
    "reject": (DocStatus.PENDING, DocStatus.DRAFT, Perm.DOC_VALIDATE, "document.rejected"),
}


def transition(db: Session, principal, doc: Document, action: str, comment: str = "") -> Document:
    if action not in TRANSITIONS:
        raise BusinessError("Action de workflow inconnue", 400)
    src, dst, perm, event = TRANSITIONS[action]
    if not principal.can(perm):
        raise BusinessError(f"Permission manquante : {perm}", 403)
    if doc.status != src:
        raise BusinessError(f"Transition « {action} » impossible depuis le statut {doc.status}", 409)
    if action == "reject" and len(comment.strip()) < 3:
        raise BusinessError("Le motif du rejet est obligatoire", 422)
    if action in ("approve", "reject") and principal.user_id and principal.user_id == doc.created_by \
            and principal.role != "admin":
        raise BusinessError("Séparation des tâches : l'auteur ne peut pas valider son propre document", 403)
    current = doc.current_version
    if action == "submit" and not current:
        raise BusinessError("Aucune version à soumettre", 409)

    doc.status = dst
    now = datetime.now(timezone.utc)
    if action == "approve":
        doc.validated_at = now
        current.is_frozen = True  # lecture seule définitive pour cette version
    db.add(WorkflowEvent(document_id=doc.id, from_status=src, to_status=dst, actor_id=principal.user_id,
                         actor_name=principal.name, comment=comment))
    audit.log(db, principal.actor, f"WORKFLOW_{action.upper()}", "document", doc.id,
              {"from": src, "to": dst, "comment": comment, "version": current.label if current else None},
              commit=False)
    db.commit()
    db.refresh(doc)
    events.emit(db, event, {"id": doc.id, "reference": doc.reference, "title": doc.title,
                            "status": doc.status, "comment": comment, "by": principal.name})
    _notify(db, action, doc, principal.name, comment)
    return doc


def _notify(db: Session, action: str, doc: Document, by: str, comment: str) -> None:
    if action == "submit":
        to = db.execute(select(User.email).join(Role).where(User.is_active.is_(True), Role.name.in_(
            ["validateur", "admin"]))).scalars().all()
        events.send_email(list(to), f"[GEDarchive] À valider : {doc.reference} - {doc.title}",
                          f"{by} a soumis le document {doc.reference} « {doc.title} » à validation.")
    elif doc.creator and doc.creator.email:
        verdict = "validé" if action == "approve" else "rejeté"
        events.send_email([doc.creator.email], f"[GEDarchive] Document {verdict} : {doc.reference}",
                          f"Votre document « {doc.title} » a été {verdict} par {by}.\n{comment}")


def history(db: Session, doc_id: str) -> list[WorkflowEvent]:
    return db.execute(select(WorkflowEvent).where(WorkflowEvent.document_id == doc_id)
                      .order_by(WorkflowEvent.id)).scalars().all()
