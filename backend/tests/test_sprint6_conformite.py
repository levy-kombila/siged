"""Sprint 6 — Journal d'audit inaltérable, intégrité SHA-256, DUA & sort final, gel, AIP OAIS."""
import hashlib
import io
import json
import zipfile
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import text

from app.models import Document
from tests.conftest import make_pdf, upload


def _validate(client, admin, make_user, **over):
    author = make_user(f"aut{abs(hash(str(over))) % 10**6}", "contributeur")
    did = upload(client, author, **over).json()["id"]
    client.post(f"/api/documents/{did}/submit", headers=author)
    client.post(f"/api/documents/{did}/approve", headers=admin)
    return did


def test_audit_chain_valid(client, admin):
    upload(client, admin)
    r = client.get("/api/audit/verify", headers=admin).json()
    assert r["valid"] is True and r["entries_checked"] >= 3


def test_audit_tampering_detected(client, admin, db):
    upload(client, admin)
    if db.get_bind().dialect.name == "postgresql":
        pytest.skip("PostgreSQL bloque la modification (testé séparément)")
    db.execute(text("UPDATE audit_logs SET actor='pirate' WHERE id=2"))
    db.commit()
    r = client.get("/api/audit/verify", headers=admin).json()
    assert r["valid"] is False and r["broken_at_id"] == 2


def test_audit_is_append_only_in_postgres(client, admin, db):
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("Trigger spécifique PostgreSQL")
    with pytest.raises(Exception, match="ajout seul"):
        db.execute(text("UPDATE audit_logs SET actor='pirate' WHERE id=1"))
    db.rollback()
    with pytest.raises(Exception, match="ajout seul"):
        db.execute(text("DELETE FROM audit_logs"))
    db.rollback()


def test_consultations_are_traced(client, admin):
    did = upload(client, admin).json()["id"]
    client.get(f"/api/documents/{did}", headers=admin)
    client.get(f"/api/documents/{did}/preview", headers=admin)
    client.get(f"/api/documents/{did}/download", headers=admin)
    actions = [e["action"] for e in client.get(f"/api/documents/{did}/audit", headers=admin).json()]
    for a in ("DOCUMENT_CREATE", "DOCUMENT_VIEW", "DOCUMENT_PREVIEW", "DOCUMENT_DOWNLOAD"):
        assert a in actions


def test_integrity_check_detects_tampering(client, admin, settings, db):
    did = upload(client, admin, make_pdf("intègre")).json()["id"]
    upload(client, admin, make_pdf("autre"))
    r = client.post("/api/admin/integrity/run", headers=admin).json()
    assert r["files_checked"] == 2 and r["failures"] == []
    # altération physique du fichier stocké
    doc = db.get(Document, did)
    f = Path(settings.storage_local_path) / doc.versions[0].storage_key
    raw = bytearray(f.read_bytes())
    raw[-5] ^= 0x01
    f.write_bytes(bytes(raw))
    r = client.post("/api/admin/integrity/run", headers=admin).json()
    assert len(r["failures"]) == 1 and r["failures"][0]["document_id"] == did
    v = client.get(f"/api/documents/{did}/versions/{doc.versions[0].id}/verify", headers=admin).json()
    assert v["intact"] is False
    assert "INTEGRITY_FAILURE" in [e["action"] for e in client.get(f"/api/documents/{did}/audit", headers=admin).json()]


def test_retention_due_and_dry_run(client, admin, make_user):
    old = _validate(client, admin, make_user, document_date="2010-01-01", dua_years=5, title="Ancienne facture")
    _validate(client, admin, make_user, document_date="2025-01-01", dua_years=10, title="Récente")
    upload(client, admin, document_date="2000-01-01", dua_years=1, title="Brouillon ancien")  # non validé
    due = client.get("/api/retention/due", headers=admin).json()
    assert [d["id"] for d in due] == [old]
    rep = client.post("/api/retention/run", headers=admin, json={"dry_run": True}).json()
    assert len(rep["destroyed"]) == 1
    assert client.get(f"/api/documents/{old}", headers=admin).json()["status"] == "VALIDATED"


def test_retention_destroy(client, admin, make_user, settings, db):
    did = _validate(client, admin, make_user, document_date="2010-01-01", dua_years=5, final_disposition="DESTROY")
    key = db.get(Document, did).versions[0].storage_key
    assert (Path(settings.storage_local_path) / key).exists()
    rep = client.post("/api/retention/run", headers=admin, json={"dry_run": False}).json()
    assert rep["destroyed"][0]["destroyed_files"][0]["sha256"]
    d = client.get(f"/api/documents/{did}", headers=admin).json()
    assert d["status"] == "DESTROYED" and d["disposed_at"]
    assert not (Path(settings.storage_local_path) / key).exists()
    assert client.get(f"/api/documents/{did}/preview", headers=admin).status_code in (404, 415)
    # la notice et la trace d'élimination subsistent
    actions = [e["action"] for e in client.get(f"/api/documents/{did}/audit", headers=admin).json()]
    assert "DOCUMENT_DESTROYED" in actions
    # exclu de la recherche par défaut
    assert client.get("/api/search", params={"reference": d["reference"]}, headers=admin).json()["total"] == 0


def test_retention_archive_definitive(client, admin, make_user):
    did = _validate(client, admin, make_user, document_date="2000-01-01", dua_years=10, final_disposition="ARCHIVE",
                    title="Délibération")
    client.post("/api/retention/run", headers=admin, json={"dry_run": False})
    d = client.get(f"/api/documents/{did}", headers=admin).json()
    assert d["status"] == "ARCHIVED"
    r = client.post(f"/api/documents/{did}/versions", headers=admin,
                    files={"file": ("x.pdf", make_pdf("modif"), "application/pdf")})
    assert r.status_code == 409


def test_legal_hold_blocks_disposal(client, admin, make_user):
    did = _validate(client, admin, make_user, document_date="2010-01-01", dua_years=1)
    r = client.put(f"/api/documents/{did}/legal-hold", headers=admin, json={"legal_hold": True, "reason": "Contentieux"})
    assert r.json()["legal_hold"] is True
    assert client.get("/api/retention/due", headers=admin).json() == []
    rep = client.post("/api/retention/run", headers=admin, json={"dry_run": False}).json()
    assert rep["destroyed"] == []


def test_retention_until_leap_day():
    from app.models import compute_retention_until
    assert compute_retention_until(date(2024, 2, 29), 1) == date(2025, 2, 28)


def test_aip_export_oais(client, admin, make_user):
    content = make_pdf("Convention de partenariat")
    did = upload(client, admin, content, title="Convention", doc_type="convention",
                 dua_years=30, final_disposition="ARCHIVE").json()["id"]
    r = client.get(f"/api/documents/{did}/aip", headers=admin)
    assert r.status_code == 200
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = z.namelist()
    assert {"bagit.txt", "manifest-sha256.txt", "metadata/description.json", "metadata/pdi.json"} <= set(names)
    assert z.read("data/v1.0/original.pdf") == content
    for line in z.read("manifest-sha256.txt").decode().strip().splitlines():
        digest, path = line.split("  ")
        assert hashlib.sha256(z.read(path)).hexdigest() == digest
    pdi = json.loads(z.read("metadata/pdi.json"))
    assert pdi["fixity_information"][0]["original_sha256"] == hashlib.sha256(content).hexdigest()
    assert any(p["action"] == "DOCUMENT_CREATE" for p in pdi["provenance_information"])


def test_delete_only_drafts(client, admin, make_user):
    did = upload(client, admin).json()["id"]
    assert client.delete(f"/api/documents/{did}", headers=admin).status_code == 422  # motif obligatoire
    assert client.delete(f"/api/documents/{did}", params={"reason": "Erreur de dépôt"}, headers=admin).status_code == 204
    assert client.get(f"/api/documents/{did}", headers=admin).json()["status"] == "DESTROYED"
    validated = _validate(client, admin, make_user)
    assert client.delete(f"/api/documents/{validated}", params={"reason": "test"}, headers=admin).status_code == 409


def test_audit_chain_survives_concurrency(client, admin):
    """Des écritures concurrentes (requêtes + tâches de fond) ne doivent pas fourcher la chaîne."""
    from concurrent.futures import ThreadPoolExecutor

    from app.core.database import SessionLocal
    from app.services import audit as audit_svc

    def write(i):
        with SessionLocal() as s:
            audit_svc.log(s, audit_svc.SYSTEM, "CONCURRENCY_TEST", "test", str(i))

    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(write, range(80)))
    r = client.get("/api/audit/verify", headers=admin).json()
    assert r["valid"] is True, r
