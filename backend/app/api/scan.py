"""API Numérisation : photos de pages -> document PDF, et QR code pour ouvrir la page sur un téléphone."""
import io
import json
from urllib.parse import urlsplit

import segno
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.documents import parse_meta, schedule_processing
from app.core.database import get_db
from app.core.deps import Principal, require
from app.core.security import Perm
from app.schemas import DocumentOut
from app.services import audit, documents as svc, scan

router = APIRouter(prefix="/api/scan", tags=["Numérisation"])


def _options(raw: str) -> tuple[str, list[scan.PageOptions]]:
    try:
        data = json.loads(raw or "{}")
        pages = [scan.PageOptions(corners=p.get("corners"), rotation=int(p.get("rotation", 0) or 0))
                 for p in data.get("pages", [])]
        return str(data.get("mode", "document")), pages
    except (json.JSONDecodeError, AttributeError, TypeError, ValueError) as exc:
        raise HTTPException(422, "Champ 'options' : JSON invalide") from exc


@router.post("", response_model=DocumentOut, status_code=201,
             summary="Numériser : assembler des photos de pages en un document PDF")
def create_scan(bg: BackgroundTasks, pages: list[UploadFile] = File(..., description="Photos des pages, dans l'ordre"),
                metadata: str = Form(..., description="Fiche de métadonnées (JSON), comme pour un dépôt"),
                options: str = Form("{}", description='{"mode": "document|gris|couleur", "pages": '
                                                      '[{"corners": [[x,y]x4] normalisés ou null, "rotation": 0}]}'),
                db: Session = Depends(get_db), p: Principal = Depends(require(Perm.DOC_WRITE))):
    meta = parse_meta(metadata)
    mode, page_opts = _options(options)
    if len(pages) > scan.MAX_PAGES:
        raise HTTPException(422, f"Trop de pages (maximum {scan.MAX_PAGES})")
    raws = []
    for f in pages:
        raw = f.file.read(scan.MAX_PAGE_BYTES + 1)
        if len(raw) > scan.MAX_PAGE_BYTES:
            raise HTTPException(413, "Photo trop volumineuse (25 Mo maximum par page)")
        raws.append(raw)
    result = scan.build_pdf(raws, page_opts, mode)
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in meta.title)[:80].strip("_") or "numerisation"
    received = svc.receive_stream(io.BytesIO(result.pdf), f"{safe}.pdf", "application/pdf")
    try:
        doc, version = svc.create_document(db, p.actor, received, meta, source="scan")
    finally:
        received.cleanup()
    # Traçabilité : empreinte de chaque photo d'origine (avant redressement)
    audit.log(db, p.actor, "SCAN_CAPTURE", "document", doc.id,
              {"pages": result.pages, "mode": mode, "page_sha256": result.page_hashes,
               "pdf_sha256": received.sha256})
    schedule_processing(bg, version.id)
    return doc


@router.get("/qr", summary="QR code (SVG) pour ouvrir la page Numériser sur un téléphone")
def qr_code(url: str = Query(..., max_length=500), _: Principal = Depends(require(Perm.DOC_READ))):
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise HTTPException(422, "Adresse http(s) attendue")
    buf = io.BytesIO()
    segno.make(url, error="m").save(buf, kind="svg", scale=6, border=2, dark="#1c2b6b", xmldecl=False)
    return Response(buf.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "no-store"})
