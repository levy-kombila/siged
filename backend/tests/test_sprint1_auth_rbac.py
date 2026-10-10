"""Sprint 1 — Authentification, RBAC, clés d'API, socle du journal d'audit."""
from tests.conftest import ADMIN, PASSWORD, login, upload


def test_login_ok_and_me(client, admin):
    r = client.get("/api/auth/me", headers=admin)
    assert r.status_code == 200
    assert r.json()["role"] == "admin"
    assert "document:validate" in r.json()["permissions"]


def test_login_wrong_password(client):
    r = client.post("/api/auth/login", data={"username": "admin", "password": "mauvais"})
    assert r.status_code == 401


def test_account_lockout_after_failures(client, settings):
    for _ in range(settings.max_failed_logins):
        client.post("/api/auth/login", data={"username": "admin", "password": "mauvais"})
    r = client.post("/api/auth/login", data={"username": ADMIN[0], "password": ADMIN[1]})
    assert r.status_code == 423  # verrouillé même avec le bon mot de passe


def test_unauthenticated_is_rejected(client):
    assert client.get("/api/search").status_code == 401
    assert client.get("/api/search", headers={"Authorization": "Bearer faux"}).status_code == 401


def test_password_policy(client, admin):
    r = client.post("/api/users", headers=admin, json={
        "username": "faible", "email": "f@test.ga", "password": "abc", "role": "lecteur"})
    assert r.status_code == 422


def test_rbac_reader_cannot_upload(client, make_user):
    reader = make_user("lecteur1", "lecteur")
    r = upload(client, reader)
    assert r.status_code == 403
    assert "document:write" in r.json()["detail"]


def test_rbac_contributor_cannot_manage_users(client, make_user):
    contrib = make_user("contrib1", "contributeur")
    assert client.get("/api/users", headers=contrib).status_code == 403
    assert client.get("/api/audit", headers=contrib).status_code == 403


def test_deactivated_user_cannot_login(client, admin, make_user):
    make_user("partant", "lecteur")
    uid = next(u["id"] for u in client.get("/api/users", headers=admin).json() if u["username"] == "partant")
    client.patch(f"/api/users/{uid}", headers=admin, json={"is_active": False})
    r = client.post("/api/auth/login", data={"username": "partant", "password": PASSWORD})
    assert r.status_code == 401


def test_api_key_for_erp(client, admin):
    r = client.post("/api/integrations/api-keys", headers=admin, json={"name": "ERP Sage", "role": "contributeur"})
    assert r.status_code == 201
    key = r.json()["api_key"]
    erp = {"X-API-Key": key}
    r = upload(client, erp)
    assert r.status_code == 201
    assert r.json()["source"] == "api"
    # Révocation
    client.delete(f"/api/integrations/api-keys/{client.get('/api/integrations/api-keys', headers=admin).json()[0]['id']}",
                  headers=admin)
    assert upload(client, erp).status_code == 401


def test_api_key_cannot_be_admin(client, admin):
    r = client.post("/api/integrations/api-keys", headers=admin, json={"name": "Trop puissante", "role": "admin"})
    assert r.status_code == 422


def test_login_events_are_audited(client, admin):
    client.post("/api/auth/login", data={"username": "admin", "password": "mauvais"})
    actions = [e["action"] for e in client.get("/api/audit", headers=admin).json()]
    assert "LOGIN" in actions and "LOGIN_FAILED" in actions


def test_roles_listed(client, admin):
    names = {r["name"] for r in client.get("/api/roles", headers=admin).json()}
    assert names == {"admin", "archiviste", "validateur", "contributeur", "lecteur"}


def test_login_helper(client):
    assert "Authorization" in login(client, *ADMIN)


def test_login_is_case_insensitive(client):
    assert client.post("/api/auth/login", data={"username": "Admin", "password": ADMIN[1]}).status_code == 200


def test_reset_password_script(client, monkeypatch, capsys):
    import sys

    from scripts import reinitialiser_mot_de_passe as reset

    monkeypatch.setattr(sys, "argv", ["x", "ADMIN"])
    monkeypatch.setattr(reset.getpass, "getpass", lambda _: "Nouveau#Admin2026")
    assert reset.main() == 0
    assert client.post("/api/auth/login", data={"username": "admin", "password": "Nouveau#Admin2026"}).status_code == 200
