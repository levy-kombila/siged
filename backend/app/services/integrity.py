"""Contrôle d'intégrité : recalcul périodique des empreintes SHA-256 des fichiers stockés
et comparaison avec celles enregistrées au dépôt. Toute divergence (altération,
corruption, fichier manquant, échec d'authentification AES-GCM) est tracée et notifiée."""
import hashlib
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DocumentVersion, IntegrityCheck
from app.services import audit, events
from app.services.audit import Actor
from app.services.storage import get_storage


def verify_object(key: str, expected: str) -> tuple[bool, str]:
    storage = get_storage()
    if not storage.exists(key):
        return False, "fichier manquant"
    h = hashlib.sha256()
    try:
        for chunk in storage.iter_plain(key):
            h.update(chunk)
    except Exception as exc:  # noqa: BLE001  (DecryptionError, I/O...)
        return False, f"illisible : {exc}"
    actual = h.hexdigest()
    if actual != expected:
        return False, f"empreinte divergente (attendu {expected[:12]}…, obtenu {actual[:12]}…)"
    return True, "ok"


def verify_version(v: DocumentVersion) -> list[dict]:
    failures = []
    for kind, key, digest in (("original", v.storage_key, v.sha256),
                              ("archival", v.archival_storage_key, v.archival_sha256)):
        if key and digest:
            ok, msg = verify_object(key, digest)
            if not ok:
                failures.append({"document_id": v.document_id, "version_id": v.id, "version": v.label,
                                 "kind": kind, "storage_key": key, "error": msg})
    return failures


def run_check(db: Session, actor: Actor = audit.SYSTEM) -> IntegrityCheck:
    check = IntegrityCheck()
    db.add(check)
    db.flush()
    failures, n = [], 0
    for v in db.execute(select(DocumentVersion).where(DocumentVersion.storage_key.is_not(None))).scalars():
        n += 1 + (1 if v.archival_storage_key else 0)
        failures += verify_version(v)
    check.files_checked = n
    check.failures = failures
    check.finished_at = datetime.now(timezone.utc)
    for f in failures:
        audit.log(db, actor, "INTEGRITY_FAILURE", "document", f["document_id"], f, commit=False)
    audit.log(db, actor, "INTEGRITY_CHECK", "system", str(check.id),
              {"files_checked": n, "failures": len(failures)}, commit=False)
    db.commit()
    if failures:
        events.emit(db, "integrity.failure", {"check_id": check.id, "failures": failures})
    return check
