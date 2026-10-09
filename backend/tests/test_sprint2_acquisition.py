"""Sprint 2 — Acquisition : dépôt, empreinte SHA-256, fiche de métadonnées, stockage hybride chiffré."""
import hashlib
import io
import json
from pathlib import Path

import pytest

from app.core.crypto import DecryptionError, decrypt_stream, encrypt_stream
from tests.conftest import make_pdf, meta, upload


def test_upload_creates_document_v1(client, admin):
    content = make_pdf("Facture numero 42")
    r = upload(client, admin, content)
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["reference"].startswith("DOC-")
    assert d["status"] == "DRAFT"
    v = d["current_version"]
    assert v["label"] == "1.0"
    assert v["sha256"] == hashlib.sha256(content).hexdigest()
    assert v["size_bytes"] == len(content)
    assert v["mime_type"] == "application/pdf"
    assert d["retention_until"] == "2035-03-15"  # 2025-03-15 + 10 ans


def test_mandatory_metadata(client, admin):
    for missing in ("title", "author", "document_date", "doc_type", "keywords"):
        m = meta()
        m.pop(missing)
        r = client.post("/api/documents", headers=admin, files={"file": ("a.pdf", make_pdf("x"), "application/pdf")},
                        data={"metadata": json.dumps(m)})
        assert r.status_code == 422, missing
    r = upload(client, admin, keywords=[])
    assert r.status_code == 422


def test_dua_inherited_from_classification(client, admin):
    r = upload(client, admin, dua_years=None, final_disposition=None, classification_code="RH.02",
               doc_type="bulletin-paie", keywords=["paie"])
    assert r.status_code == 201, r.text
    assert r.json()["dua_years"] == 10 and r.json()["final_disposition"] == "DESTROY"


def test_dua_required_without_classification(client, admin):
    r = upload(client, admin, dua_years=None, final_disposition=None, doc_type="inconnu", keywords=["zzz"],
               title="Sans rubrique")
    assert r.status_code == 422
    assert "DUA" in r.json()["detail"]


def test_duplicate_detection(client, admin):
    content = make_pdf("même contenu")
    assert upload(client, admin, content).status_code == 201
    r = upload(client, admin, content)
    assert r.status_code == 409
    assert "existing_document_id" in r.json()
    r = client.post("/api/documents?allow_duplicate=true", headers=admin,
                    files={"file": ("a.pdf", content, "application/pdf")}, data={"metadata": json.dumps(meta())})
    assert r.status_code == 201


def test_files_are_encrypted_at_rest(client, admin, settings):
    secret = b"DONNEES-CONFIDENTIELLES-SALAIRES"
    r = upload(client, admin, secret + b" " * 100, filename="note.txt", ctype="text/plain")
    assert r.status_code == 201
    stored = list(Path(settings.storage_local_path).rglob("*"))
    files = [p for p in stored if p.is_file()]
    assert files, "le fichier doit être stocké hors base"
    for f in files:
        raw = f.read_bytes()
        assert raw.startswith(b"SGED1\n")
        assert secret not in raw


def test_metadata_stored_separately_from_file(client, admin, db):
    """Stockage hybride : la base ne contient qu'une clé de stockage, pas le binaire."""
    from app.models import DocumentVersion
    upload(client, admin)
    v = db.query(DocumentVersion).first()
    assert v.storage_key.startswith("originals/")


def test_extra_dynamic_metadata(client, admin):
    r = upload(client, admin, extra_metadata={"numero_facture": "F-2025-042", "fournisseur": "SEEG"})
    assert r.json()["extra"]["numero_facture"] == "F-2025-042"


def test_crypto_roundtrip_and_tamper_detection():
    data = b"A" * (3 * 1024 * 1024 + 123)  # plusieurs blocs
    enc = io.BytesIO()
    encrypt_stream(io.BytesIO(data), enc)
    blob = enc.getvalue()
    assert b"".join(decrypt_stream(io.BytesIO(blob))) == data
    tampered = bytearray(blob)
    tampered[100] ^= 0xFF
    with pytest.raises(DecryptionError):
        b"".join(decrypt_stream(io.BytesIO(bytes(tampered))))
    # Troncature (suppression du dernier bloc) détectée
    first_len = int.from_bytes(blob[14:18], "big")
    truncated = blob[:18 + first_len]
    with pytest.raises(DecryptionError):
        b"".join(decrypt_stream(io.BytesIO(truncated)))


def test_mime_sniffing_ignores_lying_extension(client, admin):
    r = upload(client, admin, make_pdf("vrai pdf"), filename="image.png", ctype="image/png")
    assert r.json()["current_version"]["mime_type"] == "application/pdf"
