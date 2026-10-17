"""Sprint 8 — GEDarchive : rayonnage (archives physiques), alertes d'obsolescence, identité visuelle."""
from datetime import date, timedelta

from app.services import obsolescence
from app.services.audit import SYSTEM
from tests.conftest import upload


def _loc(client, h, code, kind, parent=None, **kw):
    r = client.post("/api/shelving", headers=h, json={"code": code, "label": code, "kind": kind, "parent_id": parent, **kw})
    assert r.status_code == 201, r.text
    return r.json()


# ------------------------------------------------------------------ Rayonnage
def test_shelving_tree_and_document_location(client, admin):
    salle = _loc(client, admin, "MAG1", "SALLE")
    ray = _loc(client, admin, "MAG1-R01", "RAYONNAGE", salle["id"])
    boite = _loc(client, admin, "MAG1-R01-B001", "BOITE", ray["id"], capacity=1)
    assert boite["path"] == "MAG1 › MAG1-R01 › MAG1-R01-B001"

    d1 = upload(client, admin, title="Contrat A").json()
    r = client.put(f"/api/documents/{d1['id']}/location", headers=admin,
                   json={"shelf_location_id": boite["id"], "physical_ref": "Liasse 3"})
    assert r.status_code == 200, r.text
    assert r.json()["shelf_location"]["code"] == "MAG1-R01-B001" and r.json()["physical_ref"] == "Liasse 3"

    tree = client.get("/api/shelving", headers=admin).json()
    assert tree[0]["code"] == "MAG1" and tree[0]["total_documents"] == 1
    assert [d["id"] for d in client.get(f"/api/shelving/{boite['id']}/documents", headers=admin).json()] == [d1["id"]]

    # Capacité atteinte
    d2 = upload(client, admin, title="Contrat B").json()
    r = client.put(f"/api/documents/{d2['id']}/location", headers=admin, json={"shelf_location_id": boite["id"]})
    assert r.status_code == 409
    # Emplacement non vide : suppression refusée ; retrait puis suppression acceptée
    assert client.delete(f"/api/shelving/{boite['id']}", headers=admin).status_code == 409
    client.put(f"/api/documents/{d1['id']}/location", headers=admin, json={"shelf_location_id": None})
    assert client.delete(f"/api/shelving/{boite['id']}", headers=admin).status_code == 204
    actions = [e["action"] for e in client.get(f"/api/documents/{d1['id']}/audit", headers=admin).json()]
    assert actions.count("DOCUMENT_LOCATION") == 2


def test_shelving_rules_and_permissions(client, admin, make_user):
    salle = _loc(client, admin, "S1", "SALLE")
    # Un niveau ne peut pas contenir un niveau plus large
    r = client.post("/api/shelving", headers=admin, json={"code": "X", "label": "X", "kind": "SITE", "parent_id": salle["id"]})
    assert r.status_code == 422
    assert client.post("/api/shelving", headers=admin, json={"code": "S1", "label": "dup", "kind": "SALLE"}).status_code == 409
    contrib = make_user("contrib8", "contributeur")
    assert client.post("/api/shelving", headers=contrib, json={"code": "Y", "label": "Y", "kind": "BOITE"}).status_code == 403
    assert client.get("/api/shelving", headers=contrib).status_code == 200
    archiviste = make_user("archi8", "archiviste")
    assert client.post("/api/shelving", headers=archiviste, json={"code": "Y", "label": "Y", "kind": "BOITE"}).status_code == 201


# ------------------------------------------------------------------ Obsolescence
def test_stage_computation():
    steps = [0, 7, 30, 90]
    assert obsolescence.stage_for(120, steps) is None
    assert obsolescence.stage_for(90, steps) == "J-90"
    assert obsolescence.stage_for(20, steps) == "J-30"
    assert obsolescence.stage_for(1, steps) == "J-7"
    assert obsolescence.stage_for(0, steps) == "ECHU" and obsolescence.stage_for(-5, steps) == "ECHU"


def test_validity_alerts_notify_creator_and_archivists(client, admin, make_user, db):
    contrib = make_user("contrib9", "contributeur")
    archi = make_user("archi9", "archiviste")
    today = date.today()
    doc = upload(client, contrib, title="Attestation fiscale", document_date=today.isoformat(), dua_years=10,
                 valid_until=(today + timedelta(days=20)).isoformat()).json()
    assert doc["valid_until"] == (today + timedelta(days=20)).isoformat()

    up = client.get("/api/obsolescence/upcoming?days=30", headers=contrib).json()
    assert [(i["kind"], i["days_left"], i["document"]["id"]) for i in up] == [("VALIDITY", 20, doc["id"])]

    res = obsolescence.run_alerts(db, SYSTEM, today)
    assert res["created"] == 3  # déposant + archiviste + admin
    assert obsolescence.run_alerts(db, SYSTEM, today)["created"] == 0  # idempotent

    n = client.get("/api/notifications", headers=contrib).json()
    assert n["unread"] == 1 and n["items"][0]["stage"] == "J-30" and n["items"][0]["kind"] == "VALIDITY"
    assert client.get("/api/notifications", headers=archi).json()["unread"] == 1

    # Palier suivant : nouvelle alerte ; échéance passée : alerte « ECHU »
    assert obsolescence.run_alerts(db, SYSTEM, today + timedelta(days=15))["created"] == 3
    assert obsolescence.run_alerts(db, SYSTEM, today + timedelta(days=21))["created"] == 3
    stages = [x["stage"] for x in client.get("/api/notifications", headers=contrib).json()["items"]]
    assert sorted(stages) == ["ECHU", "J-30", "J-7"]

    # Lecture
    first = client.get("/api/notifications", headers=contrib).json()["items"][0]
    assert client.post(f"/api/notifications/{first['id']}/read", headers=contrib).json()["read_at"]
    assert client.post(f"/api/notifications/{first['id']}/read", headers=archi).status_code == 404  # pas la sienne
    assert client.post("/api/notifications/read-all", headers=contrib).json()["updated"] == 2
    assert client.get("/api/notifications", headers=contrib).json()["unread"] == 0


def test_retention_alert_skipped_under_legal_hold(client, admin, db):
    old = (date.today() - timedelta(days=400)).isoformat()
    doc = upload(client, admin, title="Vieux PV", document_date=old, dua_years=1).json()
    assert [i["kind"] for i in client.get("/api/obsolescence/upcoming?days=0", headers=admin).json()] == ["RETENTION"]
    client.put(f"/api/documents/{doc['id']}/legal-hold", headers=admin, json={"legal_hold": True, "reason": "contentieux"})
    assert client.get("/api/obsolescence/upcoming?days=0", headers=admin).json() == []
    assert obsolescence.run_alerts(db, SYSTEM)["created"] == 0


def test_validity_editable_and_clearable_on_draft(client, admin):
    doc = upload(client, admin, title="Agrément").json()
    d = (date.today() + timedelta(days=60)).isoformat()
    assert client.patch(f"/api/documents/{doc['id']}", headers=admin, json={"valid_until": d}).json()["valid_until"] == d
    assert client.patch(f"/api/documents/{doc['id']}", headers=admin, json={"valid_until": None}).json()["valid_until"] is None


def test_manual_run_endpoint_and_stats(client, admin, make_user):
    upload(client, admin, title="Bail", valid_until=(date.today() + timedelta(days=3)).isoformat())
    assert client.post("/api/notifications/run", headers=admin).json()["created"] == 1
    lecteur = make_user("lect8", "lecteur")
    assert client.post("/api/notifications/run", headers=lecteur).status_code == 403
    s = client.get("/api/admin/stats", headers=admin).json()
    assert s["obsolete_soon"] == 1 and s["shelved"] == 0


def test_branding(client):
    assert client.get("/openapi.json").json()["info"]["title"] == "GEDarchive API"
