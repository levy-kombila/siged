"""API Documents : dépôt, import par lot, versions, prévisualisation, workflow, gel, AIP."""
import csv
import io
import json
import os
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import quote

from fastapi import (APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query,
                     UploadFile)
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import Principal, require
from app.core.security import Perm
from app.models import AuditLog, DocStatus, Document, DocumentVersion
from app.schemas import (AuditOut, BatchResult, DocumentDetail, DocumentMetaIn, DocumentMetaUpdate,
                         DocumentOut, LegalHoldIn, VersionOut, WorkflowAction, WorkflowEventOut)
from app.services import audit, documents as svc, integrity, oais, retention, workflow
from app.services.storage import get_storage

router = APIRouter(prefix="/api/documents", tags=["Documents"])

PREVIEWABLE = ("application/pdf", "image/png", "image/jpeg", "image/gif", "image/webp", "text/plain")


def schedule_processing(bg: BackgroundTasks, version_id: str) -> None:
    if get_settings().process_in_background:
        bg.add_task(svc.process_version, version_id)
    else:
        svc.process_version(version_id)


def parse_meta(raw: str) -> DocumentMetaIn:
    try:
        return DocumentMetaIn.model_validate(json.loads(raw))
    except json.JSONDecodeError as exc:
        raise HTTPException(422, "Champ 'metadata' : JSON invalide") from exc
    except ValidationError as exc:
        raise HTTPException(422, json.loads(exc.json(include_url=False))) from exc


def get_doc(db: Session, doc_id: str) -> Document:
    doc = db.get(Document, doc_id)
    if not doc:
        raise HTTPException(404, "Document introuvable")
    return doc


def get_version(doc: Document, version_id: str | None) -> DocumentVersion:
    if version_id:
        v = next((x for x in doc.versions if x.id == version_id), None)
    else:
        v = doc.current_version
    if not v:
        raise HTTPException(404, "Version introuvable")
    return v


# ------------------------------------------------------------------ Dépôt unitaire
@router.post("", response_model=DocumentOut, status_code=201, summary="Téléverser un document")
def upload(bg: BackgroundTasks, file: UploadFile = File(...),
           metadata: str = Form(..., description="Fiche de métadonnées (JSON) : title, author, document_date, "
                                                 "doc_type, keywords[], dua_years, final_disposition, ..."),
           allow_duplicate: bool = Query(False), db: Session = Depends(get_db),
           p: Principal = Depends(require(Perm.DOC_WRITE))):
    meta = parse_meta(metadata)
    received = svc.receive_stream(file.file, file.filename, file.content_type)
    try:
        doc, version = svc.create_document(db, p.actor, received, meta,
                                           source="api" if p.api_key else "upload", allow_duplicate=allow_duplicate)
    finally:
        received.cleanup()
    schedule_processing(bg, version.id)
    return doc


# ------------------------------------------------------------------ Import par lot
@router.post("/batch", response_model=BatchResult, status_code=207,
             summary="Import par lot : plusieurs fichiers OU une archive ZIP (+ manifest.csv optionnel)")
def batch_upload(bg: BackgroundTasks, files: list[UploadFile] = File(...),
                 metadata: str = Form("{}", description="Métadonnées communes (JSON) appliquées à chaque fichier ; "
                                                        "le titre par défaut est le nom du fichier"),
                 db: Session = Depends(get_db), p: Principal = Depends(require(Perm.DOC_WRITE))):
    try:
        common = json.loads(metadata or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(422, "Champ 'metadata' : JSON invalide") from exc
    created, errors = [], []

    def ingest(stream, filename, ctype, overrides: dict):
        meta_dict = {**common, **{k: v for k, v in overrides.items() if v not in ("", None)}}
        meta_dict.setdefault("title", Path(filename).stem)
        if isinstance(meta_dict.get("keywords"), str):
            meta_dict["keywords"] = [k.strip() for k in meta_dict["keywords"].split(";") if k.strip()]
        try:
            meta = DocumentMetaIn.model_validate(meta_dict)
            received = svc.receive_stream(stream, filename, ctype)
            try:
                doc, version = svc.create_document(db, p.actor, received, meta, source="batch")
            finally:
                received.cleanup()
            schedule_processing(bg, version.id)
            created.append(DocumentOut.model_validate(doc))
        except svc.BusinessError as exc:
            db.rollback()
            errors.append({"file": filename, "error": exc.message, **exc.extra})
        except ValidationError as exc:
            errors.append({"file": filename, "error": [e["msg"] + " : " + ".".join(map(str, e["loc"]))
                                                       for e in exc.errors()]})

    for up in files:
        if up.filename.lower().endswith(".zip"):
            with tempfile.TemporaryFile() as tmp:
                while chunk := up.file.read(1024 * 1024):
                    tmp.write(chunk)
                tmp.seek(0)
                with zipfile.ZipFile(tmp) as z:
                    manifest = {}
                    if "manifest.csv" in z.namelist():
                        text = z.read("manifest.csv").decode("utf-8-sig")
                        for row in csv.DictReader(io.StringIO(text), delimiter=";" if ";" in text.splitlines()[0] else ","):
                            manifest[row.pop("filename")] = row
                    for name in z.namelist():
                        if name.endswith("/") or name == "manifest.csv" or "__MACOSX" in name:
                            continue
                        with z.open(name) as member:
                            ingest(member, Path(name).name, None, manifest.get(name, manifest.get(Path(name).name, {})))
        else:
            ingest(up.file, up.filename, up.content_type, {})
    audit.log(db, p.actor, "BATCH_IMPORT", "batch", None, {"created": len(created), "errors": len(errors)})
    return BatchResult(created=created, errors=errors)


# ------------------------------------------------------------------ Consultation
@router.get("/{doc_id}", response_model=DocumentDetail)
def read_document(doc_id: str, db: Session = Depends(get_db), p: Principal = Depends(require(Perm.DOC_READ))):
    doc = get_doc(db, doc_id)
    audit.log(db, p.actor, "DOCUMENT_VIEW", "document", doc.id)
    return doc


@router.patch("/{doc_id}", response_model=DocumentOut, summary="Modifier la fiche de métadonnées (brouillon)")
def update_document(doc_id: str, data: DocumentMetaUpdate, db: Session = Depends(get_db),
                    p: Principal = Depends(require(Perm.DOC_WRITE))):
    return svc.update_metadata(db, p.actor, get_doc(db, doc_id), data)


@router.delete("/{doc_id}", status_code=204, summary="Supprimer un brouillon jamais validé")
def delete_document(doc_id: str, reason: str = Query(..., min_length=3), db: Session = Depends(get_db),
                    p: Principal = Depends(require(Perm.DOC_DELETE))):
    doc = get_doc(db, doc_id)
    if doc.status != DocStatus.DRAFT or any(v.is_frozen for v in doc.versions):
        raise HTTPException(409, "Seul un brouillon jamais validé peut être supprimé ; "
                                 "sinon la DUA et le sort final s'appliquent")
    proof = retention.destroy_files(doc)
    audit.log(db, p.actor, "DOCUMENT_DELETE", "document", doc.id,
              {"reference": doc.reference, "reason": reason, "destroyed_files": proof}, commit=False)
    db.commit()


# ------------------------------------------------------------------ Versions
@router.get("/{doc_id}/versions", response_model=list[VersionOut])
def list_versions(doc_id: str, db: Session = Depends(get_db), _: Principal = Depends(require(Perm.DOC_READ))):
    return get_doc(db, doc_id).versions


@router.post("/{doc_id}/versions", response_model=VersionOut, status_code=201,
             summary="Déposer une nouvelle version (v1.1 mineure, v2.0 majeure)")
def new_version(doc_id: str, bg: BackgroundTasks, file: UploadFile = File(...), comment: str = Form(""),
                major: bool = Form(False), db: Session = Depends(get_db),
                p: Principal = Depends(require(Perm.DOC_WRITE))):
    doc = get_doc(db, doc_id)
    received = svc.receive_stream(file.file, file.filename, file.content_type)
    try:
        version = svc.add_version(db, p.actor, doc, received, major_bump=major, comment=comment)
    finally:
        received.cleanup()
    schedule_processing(bg, version.id)
    return version


@router.get("/{doc_id}/versions/{version_id}/verify", summary="Vérifier l'intégrité (SHA-256) d'une version")
def verify_version(doc_id: str, version_id: str, db: Session = Depends(get_db),
                   p: Principal = Depends(require(Perm.DOC_READ))):
    v = get_version(get_doc(db, doc_id), version_id)
    failures = integrity.verify_version(v)
    audit.log(db, p.actor, "INTEGRITY_VERIFY", "document", doc_id, {"version": v.label, "ok": not failures})
    return {"version": v.label, "sha256": v.sha256, "archival_sha256": v.archival_sha256,
            "intact": not failures, "failures": failures}


def _stream(doc: Document, v: DocumentVersion, kind: str):
    key = v.archival_storage_key if kind == "archival" else v.storage_key
    if not key:
        raise HTTPException(404, "Fichier indisponible (non converti ou éliminé)")
    return get_storage().iter_plain(key)


@router.get("/{doc_id}/preview", summary="Prévisualisation en ligne (sans téléchargement)")
def preview(doc_id: str, version_id: str | None = None, db: Session = Depends(get_db),
            p: Principal = Depends(require(Perm.DOC_READ))):
    doc = get_doc(db, doc_id)
    v = get_version(doc, version_id)
    if v.archival_storage_key:
        kind, mime = "archival", "application/pdf"
    elif v.mime_type in PREVIEWABLE:
        kind, mime = "original", v.mime_type
    else:
        raise HTTPException(415, "Aperçu indisponible pour ce format (conversion PDF/A en attente ou impossible)")
    stream = _stream(doc, v, kind)
    audit.log(db, p.actor, "DOCUMENT_PREVIEW", "document", doc.id, {"version": v.label, "kind": kind})
    return StreamingResponse(stream, media_type=mime, headers={
        "Content-Disposition": "inline", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


def _pdf_for_render(v: DocumentVersion) -> str | None:
    if v.archival_storage_key:
        return v.archival_storage_key
    if v.mime_type == "application/pdf" and v.storage_key:
        return v.storage_key
    return None


@router.get("/{doc_id}/preview/pages", summary="Nombre de pages pour l'aperçu image")
def preview_pages(doc_id: str, version_id: str | None = None, db: Session = Depends(get_db),
                  _: Principal = Depends(require(Perm.DOC_READ))):
    v = get_version(get_doc(db, doc_id), version_id)
    key = _pdf_for_render(v)
    if not key:
        return {"pages": 0, "mime_type": v.mime_type}
    import pypdfium2 as pdfium
    with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
        get_storage().read_to_file(key, tmp.name)
        return {"pages": len(pdfium.PdfDocument(tmp.name)), "mime_type": "application/pdf"}


@router.get("/{doc_id}/preview/page/{page}", summary="Aperçu d'une page en image PNG (tous navigateurs, mobile)")
def preview_page(doc_id: str, page: int, version_id: str | None = None, width: int = Query(1000, ge=200, le=2000),
                 db: Session = Depends(get_db), p: Principal = Depends(require(Perm.DOC_READ))):
    doc = get_doc(db, doc_id)
    v = get_version(doc, version_id)
    key = _pdf_for_render(v)
    if not key:
        raise HTTPException(415, "Aperçu image indisponible pour ce format")
    import pypdfium2 as pdfium
    with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
        get_storage().read_to_file(key, tmp.name)
        pdf = pdfium.PdfDocument(tmp.name)
        if not 1 <= page <= len(pdf):
            raise HTTPException(404, "Page inexistante")
        pg = pdf[page - 1]
        img = pg.render(scale=width / pg.get_width()).to_pil()
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        pdf.close()
    if page == 1:
        audit.log(db, p.actor, "DOCUMENT_PREVIEW", "document", doc.id, {"version": v.label, "kind": "image"})
    return Response(buf.getvalue(), media_type="image/png", headers={"Cache-Control": "private, max-age=300"})


@router.get("/{doc_id}/download", summary="Télécharger l'original ou la version PDF/A")
def download(doc_id: str, version_id: str | None = None, format: str = Query("original", pattern="^(original|archival)$"),
             db: Session = Depends(get_db), p: Principal = Depends(require(Perm.DOC_READ))):
    doc = get_doc(db, doc_id)
    v = get_version(doc, version_id)
    stream = _stream(doc, v, format)
    name = v.original_filename if format == "original" else f"{Path(v.original_filename).stem}_v{v.label}_PDFA.pdf"
    audit.log(db, p.actor, "DOCUMENT_DOWNLOAD", "document", doc.id, {"version": v.label, "format": format})
    return StreamingResponse(stream, media_type=v.mime_type if format == "original" else "application/pdf",
                             headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}",
                                      "Cache-Control": "no-store"})


# ------------------------------------------------------------------ Workflow
def _wf(action: str):
    def handler(doc_id: str, body: WorkflowAction | None = None, db: Session = Depends(get_db),
                p: Principal = Depends(require(Perm.DOC_READ))):
        return workflow.transition(db, p, get_doc(db, doc_id), action, (body.comment if body else ""))
    return handler


router.add_api_route("/{doc_id}/submit", _wf("submit"), methods=["POST"], response_model=DocumentOut,
                     summary="Soumettre à validation (Brouillon → En validation)", tags=["Workflow"])
router.add_api_route("/{doc_id}/approve", _wf("approve"), methods=["POST"], response_model=DocumentOut,
                     summary="Approuver (En validation → Validé)", tags=["Workflow"])
router.add_api_route("/{doc_id}/reject", _wf("reject"), methods=["POST"], response_model=DocumentOut,
                     summary="Rejeter avec motif (En validation → Brouillon)", tags=["Workflow"])


@router.get("/{doc_id}/workflow", response_model=list[WorkflowEventOut], tags=["Workflow"])
def workflow_history(doc_id: str, db: Session = Depends(get_db), _: Principal = Depends(require(Perm.DOC_READ))):
    get_doc(db, doc_id)
    return workflow.history(db, doc_id)


# ------------------------------------------------------------------ Traçabilité & conservation
@router.get("/{doc_id}/audit", response_model=list[AuditOut], summary="Piste d'audit du document")
def document_audit(doc_id: str, db: Session = Depends(get_db), _: Principal = Depends(require(Perm.AUDIT_READ))):
    return db.execute(select(AuditLog).where(AuditLog.object_id == doc_id).order_by(AuditLog.id)).scalars().all()


@router.put("/{doc_id}/legal-hold", response_model=DocumentOut, summary="Poser / lever un gel juridique")
def legal_hold(doc_id: str, data: LegalHoldIn, db: Session = Depends(get_db),
               p: Principal = Depends(require(Perm.RETENTION_MANAGE))):
    doc = get_doc(db, doc_id)
    doc.legal_hold = data.legal_hold
    audit.log(db, p.actor, "LEGAL_HOLD_SET" if data.legal_hold else "LEGAL_HOLD_RELEASED", "document", doc.id,
              {"reason": data.reason}, commit=False)
    db.commit()
    db.refresh(doc)
    return doc


@router.get("/{doc_id}/aip", summary="Exporter le paquet d'archives OAIS (AIP, ZIP BagIt)")
def export_aip(doc_id: str, db: Session = Depends(get_db), p: Principal = Depends(require(Perm.RETENTION_MANAGE))):
    doc = get_doc(db, doc_id)
    if doc.status == DocStatus.DESTROYED:
        raise HTTPException(409, "Document éliminé")
    path = oais.build_aip(db, doc)
    audit.log(db, p.actor, "AIP_EXPORT", "document", doc.id, {"reference": doc.reference})
    return FileResponse(path, media_type="application/zip", filename=f"AIP_{doc.reference}.zip",
                        background=BackgroundTask(os.unlink, path))

