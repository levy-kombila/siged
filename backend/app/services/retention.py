"""Gestion de la DUA (Durée d'Utilité Administrative) et application du sort final.

* Un document VALIDÉ dont la DUA est échue (retention_until <= aujourd'hui) et qui
  n'est pas sous gel juridique est « éligible ».
* Sort final DESTROY : suppression physique de toutes les versions (originaux + PDF/A),
  effacement du texte indexé ; la notice descriptive et la trace d'élimination
  (empreintes des fichiers détruits) sont conservées -> certificat d'élimination.
* Sort final ARCHIVE : versement en archivage définitif (statut ARCHIVED, lecture seule,
  paquet AIP exportable).
Par défaut le job quotidien produit le bordereau et ne l'exécute que si
SIGED_RETENTION_AUTO_EXECUTE=true ; sinon l'archiviste confirme via l'API.
"""
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DocStatus, Document, FinalDisposition
from app.services import audit, events
from app.services.audit import Actor
from app.services.storage import get_storage


def due_documents(db: Session, today: date | None = None) -> list[Document]:
    today = today or date.today()
    return db.execute(select(Document).where(
        Document.status == DocStatus.VALIDATED,
        Document.legal_hold.is_(False),
        Document.retention_until <= today,
    ).order_by(Document.retention_until)).unique().scalars().all()


def upcoming(db: Session, until: date) -> list[Document]:
    return db.execute(select(Document).where(
        Document.status.in_([DocStatus.VALIDATED, DocStatus.DRAFT, DocStatus.PENDING]),
        Document.retention_until <= until,
    ).order_by(Document.retention_until)).unique().scalars().all()


def run(db: Session, actor: Actor, document_ids: list[str] | None = None, dry_run: bool = True,
        today: date | None = None) -> dict:
    due = due_documents(db, today)
    if document_ids is not None:
        wanted = set(document_ids)
        due = [d for d in due if d.id in wanted]
    report = {"dry_run": dry_run, "executed_at": datetime.now(timezone.utc).isoformat(),
              "destroyed": [], "archived": [], "errors": []}
    for doc in due:
        entry = {"id": doc.id, "reference": doc.reference, "title": doc.title,
                 "retention_until": doc.retention_until.isoformat(), "final_disposition": doc.final_disposition}
        if dry_run:
            (report["destroyed"] if doc.final_disposition == FinalDisposition.DESTROY
             else report["archived"]).append(entry)
            continue
        try:
            if doc.final_disposition == FinalDisposition.DESTROY:
                entry["destroyed_files"] = destroy_files(doc)
                report["destroyed"].append(entry)
                action, event = "DOCUMENT_DESTROYED", "document.destroyed"
            else:
                _archive(doc)
                report["archived"].append(entry)
                action, event = "DOCUMENT_ARCHIVED", "document.archived"
            doc.disposed_at = datetime.now(timezone.utc)
            audit.log(db, actor, action, "document", doc.id, entry, commit=False)
            db.commit()
            events.emit(db, event, {"id": doc.id, "reference": doc.reference})
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            report["errors"].append({**entry, "error": str(exc)})
    audit.log(db, actor, "RETENTION_RUN", "retention", None,
              {"dry_run": dry_run, "destroyed": len(report["destroyed"]),
               "archived": len(report["archived"]), "errors": len(report["errors"])})
    return report


def destroy_files(doc: Document) -> list[dict]:
    storage = get_storage()
    proof = []
    for v in doc.versions:
        for key, digest in ((v.storage_key, v.sha256), (v.archival_storage_key, v.archival_sha256)):
            if key:
                storage.delete(key)
                proof.append({"version": v.label, "storage_key": key, "sha256": digest})
        v.storage_key = None
        v.archival_storage_key = None
        v.extracted_text = None
        v.is_frozen = True
    doc.status = DocStatus.DESTROYED
    return proof


def _archive(doc: Document) -> None:
    for v in doc.versions:
        v.is_frozen = True
    doc.status = DocStatus.ARCHIVED
