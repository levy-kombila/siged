"""Sprint 5 — Prévisualisation, gestion des versions, circuit de validation, notifications."""
import hashlib
import hmac
import json

from app.services import events
from tests.conftest import make_pdf, upload


def _new_version(client, headers, doc_id, content, major=False, comment=""):
    return client.post(f"/api/documents/{doc_id}/versions", headers=headers,
                       files={"file": ("v.pdf", content, "application/pdf")},
                       data={"major": str(major).lower(), "comment": comment})


def test_preview_inline_without_download(client, admin):
    content = make_pdf("Aperçu")
    doc = upload(client, admin, content).json()
    r = client.get(f"/api/documents/{doc['id']}/preview", headers=admin)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"] == "inline"
    assert r.content == content  # déchiffré à la volée


def test_download_original(client, admin):
    content = make_pdf("Téléchargement")
    doc = upload(client, admin, content, filename="rapport final.pdf").json()
    r = client.get(f"/api/documents/{doc['id']}/download", headers=admin)
    assert r.content == content
    assert "attachment" in r.headers["content-disposition"]


def test_minor_and_major_versions_keep_history(client, admin):
    v1 = make_pdf("v1")
    doc = upload(client, admin, v1).json()
    assert _new_version(client, admin, doc["id"], make_pdf("v1.1")).json()["label"] == "1.1"
    assert _new_version(client, admin, doc["id"], make_pdf("v2"), major=True).json()["label"] == "2.0"
    versions = client.get(f"/api/documents/{doc['id']}/versions", headers=admin).json()
    assert [v["label"] for v in versions] == ["1.0", "1.1", "2.0"]
    assert [v["is_current"] for v in versions] == [False, False, True]
    # l'historique n'est pas écrasé : la v1.0 reste téléchargeable à l'identique
    r = client.get(f"/api/documents/{doc['id']}/download", params={"version_id": versions[0]["id"]}, headers=admin)
    assert r.content == v1


def test_identical_version_refused(client, admin):
    c = make_pdf("same")
    doc = upload(client, admin, c).json()
    assert _new_version(client, admin, doc["id"], c).status_code == 409


def test_full_workflow(client, admin, make_user):
    author = make_user("redacteur", "contributeur")
    validator = make_user("chef", "validateur")
    doc = upload(client, author).json()
    did = doc["id"]
    # le contributeur ne peut pas approuver
    assert client.post(f"/api/documents/{did}/approve", headers=author).status_code == 403  # droit manquant
    assert client.post(f"/api/documents/{did}/submit", headers=author).json()["status"] == "PENDING_VALIDATION"
    assert client.post(f"/api/documents/{did}/approve", headers=author).status_code == 403
    # aucune nouvelle version pendant la validation
    assert _new_version(client, author, did, make_pdf("pendant")).status_code == 409
    # rejet sans motif interdit
    assert client.post(f"/api/documents/{did}/reject", headers=validator, json={"comment": ""}).status_code == 422
    r = client.post(f"/api/documents/{did}/reject", headers=validator, json={"comment": "Montant erroné"})
    assert r.json()["status"] == "DRAFT"
    client.post(f"/api/documents/{did}/submit", headers=author)
    r = client.post(f"/api/documents/{did}/approve", headers=validator, json={"comment": "OK"})
    assert r.json()["status"] == "VALIDATED"
    assert r.json()["current_version"]["is_frozen"] is True
    hist = client.get(f"/api/documents/{did}/workflow", headers=author).json()
    assert [(h["from_status"], h["to_status"]) for h in hist] == [
        ("DRAFT", "PENDING_VALIDATION"), ("PENDING_VALIDATION", "DRAFT"),
        ("DRAFT", "PENDING_VALIDATION"), ("PENDING_VALIDATION", "VALIDATED")]


def test_validated_document_is_frozen(client, admin, make_user):
    author = make_user("auteur2", "contributeur")
    validator = make_user("valid2", "validateur")
    did = upload(client, author).json()["id"]
    client.post(f"/api/documents/{did}/submit", headers=author)
    client.post(f"/api/documents/{did}/approve", headers=validator)
    # métadonnées figées
    assert client.patch(f"/api/documents/{did}", headers=author, json={"title": "Nouveau"}).status_code == 409
    # une modification force une version majeure et repasse en brouillon
    v = _new_version(client, author, did, make_pdf("correction"))
    assert v.json()["label"] == "2.0"
    d = client.get(f"/api/documents/{did}", headers=author).json()
    assert d["status"] == "DRAFT"
    assert d["versions"][0]["is_frozen"] is True  # la v1.0 validée reste figée


def test_separation_of_duties(client, make_user):
    both = make_user("polyvalent", "validateur")
    # un validateur sans droit d'écriture ne peut pas déposer
    assert upload(client, both).status_code == 403


def test_author_cannot_self_validate(client, admin, make_user, db):
    from app.core.security import Perm
    from app.models import Role
    role = db.query(Role).filter_by(name="validateur").one()
    role.permissions = role.permissions + [Perm.DOC_WRITE]
    db.commit()
    v = make_user("autovalid", "validateur")
    did = upload(client, v).json()["id"]
    client.post(f"/api/documents/{did}/submit", headers=v)
    r = client.post(f"/api/documents/{did}/approve", headers=v)
    assert r.status_code == 403 and "Séparation" in r.json()["detail"]


def test_metadata_update_in_draft_is_audited(client, admin):
    did = upload(client, admin).json()["id"]
    r = client.patch(f"/api/documents/{did}", headers=admin, json={"title": "Titre corrigé", "dua_years": 5})
    assert r.json()["title"] == "Titre corrigé"
    assert r.json()["retention_until"] == "2030-03-15"
    trail = client.get(f"/api/documents/{did}/audit", headers=admin).json()
    upd = next(e for e in trail if e["action"] == "METADATA_UPDATE")
    assert upd["details"]["changes"]["title"]["new"] == "Titre corrigé"


def test_webhooks_signed(client, admin, make_user):
    sent = []
    events._sender_override = lambda url, headers, body: sent.append((url, headers, body))
    r = client.post("/api/integrations/webhooks", headers=admin,
                    json={"name": "SIRH", "url": "https://sirh.local/hook", "events": ["document.validated"]})
    secret = r.json()["secret"]
    author = make_user("auteur3", "contributeur")
    validator = make_user("valid3", "validateur")
    did = upload(client, author).json()["id"]
    client.post(f"/api/documents/{did}/submit", headers=author)
    client.post(f"/api/documents/{did}/approve", headers=validator)
    assert len(sent) == 1
    url, headers, body = sent[0]
    assert headers["X-SIGED-Event"] == "document.validated"
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert headers["X-SIGED-Signature"] == expected
    assert json.loads(body)["data"]["id"] == did


def test_preview_as_page_images(client, admin):
    doc = upload(client, admin, make_pdf("Page unique")).json()
    info = client.get(f"/api/documents/{doc['id']}/preview/pages", headers=admin).json()
    assert info["pages"] == 1
    r = client.get(f"/api/documents/{doc['id']}/preview/page/1", headers=admin)
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert r.content[:4] == b"\x89PNG"
    assert client.get(f"/api/documents/{doc['id']}/preview/page/2", headers=admin).status_code == 404
