"""Capture automatique depuis un dossier partagé (« hot folder »).

Déposez dans SIGED_INBOX_PATH :
    facture_0042.pdf
    facture_0042.pdf.json   <- (optionnel) fiche de métadonnées JSON
Sans fiche, les métadonnées par défaut de <inbox>/_defaults.json sont utilisées.
Un sous-dossier portant un code du plan de classement (ex. inbox/FIN.01/) classe
automatiquement les fichiers qu'il contient.
Après traitement : déplacement vers _processed/ ou _errors/ (avec un .error.txt).
"""
import json
import logging
import shutil
import time
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.schemas import DocumentMetaIn
from app.services import documents as svc
from app.services.audit import Actor

logger = logging.getLogger("siged.hotfolder")
HOTFOLDER_ACTOR = Actor(None, "system:hotfolder")
RESERVED = {"_processed", "_errors"}
MIN_AGE_SECONDS = 5  # évite de capturer un fichier en cours de copie


def _defaults(inbox: Path) -> dict:
    f = inbox / "_defaults.json"
    if f.exists():
        return json.loads(f.read_text())
    return {"author": "Capture automatique", "doc_type": "courrier", "keywords": ["capture"]}


def scan(inbox: Path | None = None, min_age: int = MIN_AGE_SECONDS) -> dict:
    inbox = Path(inbox or get_settings().inbox_path)
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / "_processed").mkdir(exist_ok=True)
    (inbox / "_errors").mkdir(exist_ok=True)
    defaults = _defaults(inbox)
    result = {"processed": [], "errors": []}
    now = time.time()
    for path in sorted(inbox.rglob("*")):
        rel = path.relative_to(inbox)
        if (not path.is_file() or rel.parts[0] in RESERVED or path.name.startswith(("_", "."))
                or path.suffix == ".json" or now - path.stat().st_mtime < min_age):
            continue
        meta_file = path.with_name(path.name + ".json")
        meta = {**defaults, "title": path.stem.replace("_", " "), "document_date": date.today().isoformat()}
        if len(rel.parts) > 1:
            meta["classification_code"] = rel.parts[0]
        if meta_file.exists():
            meta.update(json.loads(meta_file.read_text()))
        db = SessionLocal()
        try:
            with open(path, "rb") as fh:
                received = svc.receive_stream(fh, path.name)
            try:
                doc, version = svc.create_document(db, HOTFOLDER_ACTOR, received,
                                                   DocumentMetaIn.model_validate(meta), source="hotfolder")
            finally:
                received.cleanup()
            svc.process_version(version.id)
            _move(path, meta_file, inbox / "_processed")
            result["processed"].append({"file": str(rel), "reference": doc.reference})
        except (svc.BusinessError, ValidationError, ValueError) as exc:
            db.rollback()
            msg = exc.message if isinstance(exc, svc.BusinessError) else str(exc)
            target = _move(path, meta_file, inbox / "_errors")
            target.with_name(target.name + ".error.txt").write_text(msg)
            result["errors"].append({"file": str(rel), "error": msg})
            logger.warning("Hot folder : %s rejeté (%s)", rel, msg)
        finally:
            db.close()
    return result


def _move(path: Path, meta_file: Path, dest_dir: Path) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = dest_dir / f"{stamp}_{path.name}"
    shutil.move(str(path), target)
    if meta_file.exists():
        shutil.move(str(meta_file), dest_dir / f"{stamp}_{meta_file.name}")
    return target
