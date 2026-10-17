"""Export d'un paquet d'archives (AIP/DIP) selon le modèle OAIS (ISO 14721).

Structure du paquet (inspirée de BagIt, RFC 8493) :
    bagit.txt
    manifest-sha256.txt          <- empreintes de chaque fichier de data/
    data/v1.0/original.<ext>     <- objets numériques (toutes les versions)
    data/v1.0/archival.pdf       <- représentation pérenne PDF/A
    metadata/description.json    <- information de description (fiche de métadonnées)
    metadata/pdi.json            <- information de pérennisation (PDI) : provenance
                                    (journal d'audit), contexte (plan de classement),
                                    intégrité (empreintes), référence (cote, UUID)
"""
import hashlib
import json
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog, Document
from app.services.storage import get_storage


def build_aip(db: Session, doc: Document) -> Path:
    storage = get_storage()
    fd = tempfile.NamedTemporaryFile(prefix=f"aip-{doc.reference}-", suffix=".zip", delete=False)
    fd.close()
    manifest = []
    with zipfile.ZipFile(fd.name, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("bagit.txt", "BagIt-Version: 1.0\nTag-File-Character-Encoding: UTF-8\n")
        for v in doc.versions:
            for kind, key, name in (("original", v.storage_key, "original" + Path(v.original_filename).suffix),
                                    ("archival", v.archival_storage_key, "archival.pdf")):
                if not key:
                    continue
                arc = f"data/v{v.label}/{name}"
                h = hashlib.sha256()
                with z.open(arc, "w", force_zip64=True) as out:
                    for chunk in storage.iter_plain(key):
                        h.update(chunk)
                        out.write(chunk)
                manifest.append(f"{h.hexdigest()}  {arc}")
        description = {
            "reference": doc.reference, "uuid": doc.id, "title": doc.title, "author": doc.author,
            "date": doc.document_date.isoformat(), "type": doc.doc_type, "keywords": doc.keywords,
            "description": doc.description, "extra_metadata": doc.extra,
        }
        trail = db.execute(select(AuditLog).where(AuditLog.object_id == doc.id).order_by(AuditLog.id)).scalars()
        pdi = {
            "reference_information": {"reference": doc.reference, "uuid": doc.id},
            "context_information": {
                "classification": {"code": doc.classification.code, "label": doc.classification.label}
                if doc.classification else None,
                "status": doc.status, "source": doc.source},
            "retention": {"dua_years": doc.dua_years, "final_disposition": doc.final_disposition,
                          "retention_until": doc.retention_until.isoformat(), "legal_hold": doc.legal_hold},
            "fixity_information": [{"version": v.label, "original_sha256": v.sha256,
                                    "archival_sha256": v.archival_sha256, "archival_format": v.archival_format,
                                    "size_bytes": v.size_bytes, "mime_type": v.mime_type,
                                    "original_filename": v.original_filename} for v in doc.versions],
            "provenance_information": [{"at": e.created_at.isoformat(), "actor": e.actor, "action": e.action,
                                        "details": e.details, "entry_hash": e.entry_hash} for e in trail],
            "package": {"generated_at": datetime.now(timezone.utc).isoformat(), "generator": "GEDarchive",
                        "standard": "ISO 14721 (OAIS) - AIP"},
        }
        z.writestr("metadata/description.json", json.dumps(description, ensure_ascii=False, indent=2, default=str))
        z.writestr("metadata/pdi.json", json.dumps(pdi, ensure_ascii=False, indent=2, default=str))
        z.writestr("manifest-sha256.txt", "\n".join(manifest) + "\n")
    return Path(fd.name)
