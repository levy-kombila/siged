"""Sprint 10 — Gestion des utilisateurs dans l'interface et changement de mot de passe."""
from tests.conftest import ADMIN, PASSWORD, login

NEW = "Nouveau#Pass2026"


def test_change_own_password(client, make_user):
    h = make_user("agent10", "contributeur")
    r = client.post("/api/auth/password", headers=h, json={"current_password": "faux", "new_password": NEW})
    assert r.status_code == 422 and "actuel" in r.json()["detail"]
    r = client.post("/api/auth/password", headers=h, json={"current_password": PASSWORD, "new_password": "court"})
    assert r.status_code == 422
    r = client.post("/api/auth/password", headers=h, json={"current_password": PASSWORD, "new_password": PASSWORD})
    assert r.status_code == 422
    assert client.post("/api/auth/password", headers=h, json={"current_password": PASSWORD, "new_password": NEW}).status_code == 204
    assert client.post("/api/auth/login", data={"username": "agent10", "password": PASSWORD}).status_code == 401
    login(client, "agent10", NEW)


def test_admin_cannot_lock_himself_out(client, admin):
    me = client.get("/api/auth/me", headers=admin).json()["user"]
    r = client.patch(f"/api/users/{me['id']}", headers=admin, json={"is_active": False})
    assert r.status_code == 409
    r = client.patch(f"/api/users/{me['id']}", headers=admin, json={"role": "lecteur"})
    assert r.status_code == 409


def test_last_active_admin_is_protected(client, admin, make_user):
    make_user("admin2", "admin")
    h2 = login(client, "admin2", PASSWORD)
    first = client.get("/api/auth/me", headers=admin).json()["user"]["id"]
    # admin2 peut rétrograder le premier admin (il en reste un) ...
    assert client.patch(f"/api/users/{first}", headers=h2, json={"role": "archiviste"}).status_code == 200
    # ... mais plus aucun autre admin actif : admin2 ne peut pas être retiré par un autre (ni par lui-même)
    me2 = client.get("/api/auth/me", headers=h2).json()["user"]["id"]
    assert client.patch(f"/api/users/{me2}", headers=h2, json={"is_active": False}).status_code == 409


def test_reactivation_unlocks_account(client, admin, make_user, settings):
    make_user("bloque", "lecteur")
    for _ in range(settings.max_failed_logins):
        client.post("/api/auth/login", data={"username": "bloque", "password": "mauvais"})
    users = {u["username"]: u for u in client.get("/api/users", headers=admin).json()}
    assert users["bloque"]["locked_until"] is not None
    r = client.patch(f"/api/users/{users['bloque']['id']}", headers=admin, json={"is_active": True})
    assert r.status_code == 200 and r.json()["locked_until"] is None
    login(client, "bloque", PASSWORD)


def test_users_screen_listed_in_interface(client):
    assert 'data-view="users"' in client.get("/").text
    assert ADMIN[0] == "admin"
