"""Service métier Documents : acquisition, empreinte, versions, métadonnées, traitement PDF/A/OCR."""
import hashlib
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import BinaryIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models import (
    ClassificationNode, ConversionStatus, DocStatus, Document, DocumentMetadata, DocumentVersion,
    Sequence, compute_retention_until,
)
from app.schemas import DocumentMetaIn, DocumentMetaUpdate
from app.services import audit, conversion, events
from app.services.audit import Actor
from app.services.classification import auto_classify
from app.services.storage import get_storage

logger = logging.getLogger("siged.documents")


class BusinessError(Exception):
    def __init__(self, message: str, status_code: int = 400, extra: dict | None = None):
        super().__init__(message)
        self.message, self.status_code, self.extra = message, status_code, extra or {}


# ------------------------------------------------------------------ Réception & empreinte
@dataclass
class ReceivedFile:
    path: Path
    filename: str
    sha256: str
    size: int
    mime: str

    def cleanup(self):
        try:
            os.unlink(self.path)
        except OSError:
            pass


def receive_stream(stream: BinaryIO, filename: str, declared_mime: str | None = None) -> ReceivedFile:
    """Écrit le flux sur disque temporaire en calculant le SHA-256 À LA VOLÉE
    (empreinte du fichier tel que reçu, avant toute transformation)."""
    max_bytes = get_settings().max_upload_mb * 1024 * 1024
    h = hashlib.sha256()
    size = 0
    head = b""
    fd, tmp = tempfile.mkstemp(prefix="siged-up-")
    try:
        with os.fdopen(fd, "wb") as out:
            while chunk := stream.read(1024 * 1024):
                if not head:
                    head = chunk[:16]
                size += len(chunk)
                if size > max_bytes:
                    raise BusinessError(f"Fichier trop volumineux (max {get_settings().max_upload_mb} Mo)", 413)
                h.update(chunk)
                out.write(chunk)
    except Exception:
        os.unlink(tmp)
        raise
    if size == 0:
        os.unlink(tmp)
        raise BusinessError("Fichier vide", 422)
    safe_name = Path(filename or "document").name[:255]
    return ReceivedFile(Path(tmp), safe_name, h.hexdigest(), size,
                        conversion.guess_mime(safe_name, declared_mime, head))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


# ------------------------------------------------------------------ Utilitaires
def next_reference(db: Session) -> str:
    year = date.today().year
    name = f"DOC-{year}"
    seq = db.execute(select(Sequence).where(Sequence.name == name).with_for_update()).scalar()
    if not seq:
        seq = Sequence(name=name, value=0)
        db.add(seq)
    seq.value += 1
    db.flush()
    return f"{name}-{seq.value:06d}"


def _resolve_classification(db: Session, meta: DocumentMetaIn) -> ClassificationNode | None:
    if meta.classification_id:
        node = db.get(ClassificationNode, meta.classification_id)
        if not node:
            raise BusinessError("Rubrique du plan de classement introuvable", 422)
        return node
    if meta.classification_code:
        node = db.execute(select(ClassificationNode).where(
            ClassificationNode.code == meta.classification_code)).scalar()
        if not node:
            raise BusinessError(f"Code de classement inconnu : {meta.classification_code}", 422)
        return node
    return auto_classify(db, meta.doc_type, meta.keywords, meta.title)


def find_duplicate(db: Session, sha256: str) -> Document | None:
    return db.execute(
        select(Document).join(DocumentVersion).where(
            DocumentVersion.sha256 == sha256, Document.status != DocStatus.DESTROYED)
    ).unique().scalars().first()


# ------------------------------------------------------------------ Création
def create_document(db: Session, actor: Actor, received: ReceivedFile, meta: DocumentMetaIn,
                    source: str = "upload", allow_duplicate: bool = False) -> tuple[Document, DocumentVersion]:
    if not allow_duplicate:
        dup = find_duplicate(db, received.sha256)
        if dup:
            raise BusinessError(f"Doublon : ce fichier existe déjà ({dup.reference})", 409,
                                {"existing_document_id": dup.id, "reference": dup.reference})
    node = _resolve_classification(db, meta)
    dua = meta.dua_years if meta.dua_years is not None else (node.default_dua_years if node else None)
    disp = meta.final_disposition or (node.default_final_disposition if node else None)
    if dua is None or disp is None:
        raise BusinessError("DUA et sort final obligatoires (non fournis et non hérités du plan de classement)", 422)

    doc = Document(
        reference=next_reference(db), title=meta.title.strip(), author=meta.author.strip(),
        document_date=meta.document_date, doc_type=meta.doc_type.strip().lower(), keywords=meta.keywords,
        dua_years=dua, final_disposition=disp, description=meta.description,
        retention_until=compute_retention_until(meta.document_date, dua),
        classification_id=node.id if node else None, status=DocStatus.DRAFT, source=source,
        created_by=actor.user_id,
    )
    db.add(doc)
    db.flush()
    for k, v in (meta.extra_metadata or {}).items():
        db.add(DocumentMetadata(document_id=doc.id, meta_key=k[:100], meta_value=str(v)))
    version = _store_version(db, actor, doc, received, 1, 0, "Version initiale")
    audit.log(db, actor, "DOCUMENT_CREATE", "document", doc.id, {
        "reference": doc.reference, "title": doc.title, "source": source, "version": "1.0",
        "sha256": received.sha256, "size": received.size, "classification": node.code if node else None,
        "auto_classified": bool(node and not meta.classification_id and not meta.classification_code),
    }, commit=False)
    db.commit()
    db.refresh(doc)
    events.emit(db, "document.created", {"id": doc.id, "reference": doc.reference, "title": doc.title})
    return doc, version


def _store_version(db: Session, actor: Actor, doc: Document, received: ReceivedFile,
                   major: int, minor: int, comment: str) -> DocumentVersion:
    version = DocumentVersion(
        document_id=doc.id, major=major, minor=minor, is_current=True, comment=comment,
        original_filename=received.filename, mime_type=received.mime, size_bytes=received.size,
        sha256=received.sha256, created_by=actor.user_id,
        conversion_status=ConversionStatus.PENDING,
    )
    db.add(version)
    db.flush()
    key = f"originals/{doc.id}/{version.id}"
    get_storage().save_file(key, received.path)
    version.storage_key = key
    return version


# ------------------------------------------------------------------ Versions
def add_version(db: Session, actor: Actor, doc: Document, received: ReceivedFile,
                major_bump: bool = False, comment: str = "") -> DocumentVersion:
    if doc.status == DocStatus.PENDING:
        raise BusinessError("Document en cours de validation : nouvelle version impossible", 409)
    if doc.status in (DocStatus.ARCHIVED, DocStatus.DESTROYED):
        raise BusinessError("Document clos (sort final appliqué) : aucune modification possible", 409)
    if doc.legal_hold:
        raise BusinessError("Document sous gel juridique", 409)
    current = doc.current_version
    if current and current.sha256 == received.sha256:
        raise BusinessError("Fichier identique à la version courante", 409)
    was_validated = doc.status == DocStatus.VALIDATED
    if was_validated:
        major_bump = True  # Un document validé est figé : toute modification ouvre une version majeure
    major = current.major + 1 if (current and major_bump) else (current.major if current else 1)
    minor = 0 if (major_bump or not current) else current.minor + 1
    for v in doc.versions:
        v.is_current = False
    version = _store_version(db, actor, doc, received, major, minor, comment)
    if was_validated:
        doc.status = DocStatus.DRAFT
        doc.validated_at = None
    doc.updated_at = datetime.now(timezone.utc)
    audit.log(db, actor, "VERSION_ADD", "document", doc.id, {
        "version": version.label, "sha256": received.sha256, "size": received.size,
        "previous": current.label if current else None, "reopened_from_validated": was_validated,
    }, commit=False)
    db.commit()
    db.refresh(doc)
    events.emit(db, "document.version_added", {"id": doc.id, "version": version.label})
    return version


# ------------------------------------------------------------------ Métadonnées
EDITABLE_STATUSES = {DocStatus.DRAFT}


def update_metadata(db: Session, actor: Actor, doc: Document, upd: DocumentMetaUpdate) -> Document:
    if doc.status not in EDITABLE_STATUSES:
        raise BusinessError(f"Métadonnées figées (statut {doc.status}) : déposez une nouvelle version", 409)
    changes = {}
    data = upd.model_dump(exclude_unset=True)
    extra = data.pop("extra_metadata", None)
    if "final_disposition" in data and data["final_disposition"] not in (None, "DESTROY", "ARCHIVE"):
        raise BusinessError("Sort final : DESTROY ou ARCHIVE", 422)
    if "keywords" in data:
        data["keywords"] = [k.strip() for k in data["keywords"] or [] if k.strip()]
        if not data["keywords"]:
            raise BusinessError("Au moins un mot-clé est obligatoire", 422)
    if "classification_id" in data and data["classification_id"] is not None:
        if not db.get(ClassificationNode, data["classification_id"]):
            raise BusinessError("Rubrique du plan de classement introuvable", 422)
    for k, v in data.items():
        if v is None and k not in ("classification_id",):
            continue
        old = getattr(doc, k)
        if old != v:
            changes[k] = {"old": old, "new": v}
            setattr(doc, k, v)
    if extra is not None:
        old_extra = doc.extra
        doc.extra_metadata.clear()
        db.flush()
        for k, v in extra.items():
            doc.extra_metadata.append(DocumentMetadata(document_id=doc.id, meta_key=k, meta_value=str(v)))
        changes["extra_metadata"] = {"old": old_extra, "new": extra}
    doc.retention_until = compute_retention_until(doc.document_date, doc.dua_years)
    if changes:
        audit.log(db, actor, "METADATA_UPDATE", "document", doc.id, {"changes": changes}, commit=False)
    db.commit()
    db.refresh(doc)
    return doc


# ------------------------------------------------------------------ Traitement asynchrone
def process_version(version_id: str) -> None:
    """Conversion PDF/A + OCR + extraction du texte. Exécuté en tâche de fond."""
    db = SessionLocal()
    try:
        v = db.get(DocumentVersion, version_id)
        if not v or not v.storage_key:
            return
        storage = get_storage()
        with conversion.new_workdir() as wd:
            wd = Path(wd)
            src = wd / "original.bin"
            storage.read_to_file(v.storage_key, src)
            try:
                res = conversion.process(src, v.original_filename, v.mime_type, wd)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Conversion échouée")
                v.conversion_status, v.conversion_log = ConversionStatus.FAILED, str(exc)[:2000]
                db.commit()
                return
            if res.pdf_path and res.pdf_path.exists():
                key = f"archival/{v.document_id}/{v.id}.pdf"
                storage.save_file(key, res.pdf_path)
                v.archival_storage_key = key
                v.archival_sha256 = sha256_file(res.pdf_path)
                v.archival_size_bytes = res.pdf_path.stat().st_size
                v.archival_format = res.archival_format
        v.extracted_text = (res.text or "").replace("\x00", "")
        v.ocr_applied = res.ocr_applied
        v.conversion_status = res.status
        v.conversion_log = "\n".join(res.log)[:4000]
        doc = v.document
        if doc.classification_id is None and v.extracted_text:
            node = auto_classify(db, doc.doc_type, doc.keywords, doc.title, v.extracted_text)
            if node:
                doc.classification_id = node.id
                v.conversion_log += f"\nClassement automatique a posteriori (texte OCR) : {node.code}"
        audit.log(db, audit.SYSTEM, "DOCUMENT_PROCESSED", "document", v.document_id, {
            "version": v.label, "status": res.status, "archival_format": v.archival_format,
            "archival_sha256": v.archival_sha256, "ocr": res.ocr_applied, "text_chars": len(v.extracted_text),
        }, commit=False)
        db.commit()
    finally:
        db.close()


def copy_to_temp(path: Path) -> Path:
    fd, tmp = tempfile.mkstemp(prefix="siged-cp-")
    os.close(fd)
    shutil.copyfile(path, tmp)
    return Path(tmp)
