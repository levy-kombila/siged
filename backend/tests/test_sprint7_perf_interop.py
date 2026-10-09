"""Sprint 7 — Performance, supervision, interface web, tableau de bord."""
import time

from app.core.database import SessionLocal
from app.models import DocStatus, Document, DocumentVersion, compute_retention_until
from tests.conftest import upload


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok", "database": True, "storage": True}


def test_process_time_header(client, admin):
    r = client.get("/api/search", headers=admin)
    assert float(r.headers["X-Process-Time-ms"]) >= 0
    assert r.headers["X-Content-Type-Options"] == "nosniff"


def test_frontend_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "SIGED" in r.text
    assert client.get("/static/app.js").status_code == 200


def test_openapi_contract(client):
    spec = client.get("/openapi.json").json()
    for path in ("/api/documents", "/api/search", "/api/documents/{doc_id}/aip", "/api/audit/verify"):
        assert path in spec["paths"]


def test_dashboard_stats(client, admin):
    upload(client, admin)
    s = client.get("/api/admin/stats", headers=admin).json()
    assert s["documents_by_status"]["DRAFT"] == 1 and s["versions"] == 1


def test_search_under_two_seconds_on_volume(client, admin):
    """Insère 2 000 notices (avec texte) puis vérifie que la recherche reste < 2 s."""
    from datetime import date
    words = "facture contrat budget convention rapport note paie courrier marche avenant".split()
    with SessionLocal() as db:
        for i in range(2000):
            w = words[i % len(words)]
            d = Document(reference=f"DOC-T-{i:06d}", title=f"{w.capitalize()} {i}", author=f"Service {i % 17}",
                         document_date=date(2015 + i % 10, 1 + i % 12, 1 + i % 28), doc_type=w, keywords=[w],
                         dua_years=10, final_disposition="DESTROY", status=DocStatus.VALIDATED,
                         retention_until=compute_retention_until(date(2015 + i % 10, 1, 1), 10))
            db.add(d)
            db.flush()
            db.add(DocumentVersion(document_id=d.id, major=1, minor=0, original_filename="x.pdf",
                                   mime_type="application/pdf", size_bytes=1, sha256="0" * 64,
                                   extracted_text=f"Texte du document {i} portant sur {w} " * 20))
        db.commit()
    for params in ({"q": "convention"}, {"doc_type": "budget", "date_from": "2020-01-01"},
                   {"author": "Service 3", "sort": "date_desc"}, {}):
        t0 = time.perf_counter()
        r = client.get("/api/search", params=params, headers=admin)
        elapsed = time.perf_counter() - t0
        assert r.status_code == 200
        print(f"PERF {params} -> {elapsed * 1000:.0f} ms")
        assert elapsed < 2.0, f"{params} : {elapsed:.2f}s"
    assert client.get("/api/search", params={"q": "convention"}, headers=admin).json()["total"] == 200


def _init_in_child(_):
    from app.core.database import init_engine, initialize
    init_engine()  # nouveau moteur dans le processus fils
    initialize()
    return True


def test_concurrent_startup_is_safe(client):
    """Les workers Uvicorn et le worker planifié (processus distincts) initialisent la base
    en même temps : le verrou de démarrage doit éviter les créations concurrentes."""
    import multiprocessing as mp

    import pytest

    from app.core.database import Base, get_engine
    from app.models import Role, User

    if get_engine().dialect.name != "postgresql":
        pytest.skip("Plusieurs processus = déploiement PostgreSQL ; SQLite sert au développement mono-processus")

    Base.metadata.drop_all(get_engine())
    get_engine().dispose()
    with mp.get_context("fork").Pool(6) as pool:
        assert all(pool.map(_init_in_child, range(6)))
    with SessionLocal() as db:
        assert db.query(Role).count() == 5
        assert db.query(User).count() == 1
