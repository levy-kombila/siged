"""Déploiement serverless (Vercel) : configuration, tâches planifiées HTTP, stockage S3 compatible."""
import pytest

from app.core.config import DEFAULT_SECRET, Settings
from tests.conftest import make_pdf, upload


def test_database_url_normalized_from_provider(monkeypatch):
    monkeypatch.delenv("SIGED_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@ep-x-pooler.neon.tech/db?sslmode=require")
    assert Settings().database_url == "postgresql+psycopg://u:p@ep-x-pooler.neon.tech/db?sslmode=require"


def test_serverless_adjustments(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    s = Settings()
    assert s.serverless and not s.process_in_background
    assert s.max_upload_mb <= 4
    assert str(s.storage_local_path).startswith("/tmp")


def test_production_guard(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("SIGED_ENVIRONMENT", "prod")
    monkeypatch.setenv("SIGED_SECRET_KEY", DEFAULT_SECRET)
    monkeypatch.setenv("SIGED_STORAGE_ENCRYPTION_KEY", "")
    monkeypatch.setenv("SIGED_DATABASE_URL", "sqlite:///./x.db")
    problems = Settings().production_problems()
    assert len(problems) == 4  # secret, clé AES, SQLite et disque local refusés en serverless prod


def test_cron_requires_secret(client, settings, monkeypatch):
    monkeypatch.setattr(settings, "cron_secret", "")
    assert client.get("/api/cron/daily").status_code == 404
    monkeypatch.setattr(settings, "cron_secret", "s3cr3t-cron-0123456789")
    assert client.get("/api/cron/daily", headers={"Authorization": "Bearer faux"}).status_code == 401


def test_cron_daily_runs_tasks(client, admin, settings, monkeypatch):
    monkeypatch.setattr(settings, "cron_secret", "s3cr3t-cron-0123456789")
    upload(client, admin, make_pdf("Pour le contrôle nocturne"))
    r = client.get("/api/cron/daily", headers={"Authorization": "Bearer s3cr3t-cron-0123456789"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["integrity"] == {"files_checked": 1, "failures": 0}
    assert body["retention"]["dry_run"] is True
    assert body["mail"] == {"skipped": True}


def test_s3_backend_roundtrip(monkeypatch, settings):
    """Stockage S3 compatible (Supabase, R2, MinIO) simulé avec moto."""
    moto = pytest.importorskip("moto")
    from app.services import storage

    with moto.mock_aws():
        monkeypatch.setattr(settings, "storage_backend", "s3")
        monkeypatch.setattr(settings, "s3_endpoint_url", "")
        monkeypatch.setattr(settings, "s3_access_key", "test")
        monkeypatch.setattr(settings, "s3_secret_key", "test")
        monkeypatch.setattr(settings, "s3_bucket", "siged-test")
        storage.reset_storage()
        st = storage.get_storage()
        assert st.ping()
        import tempfile
        data = make_pdf("Objet S3 chiffré")
        with tempfile.NamedTemporaryFile() as f:
            f.write(data)
            f.flush()
            st.save_file("originals/x/y", f.name)
        raw = st.backend.client.get_object(Bucket="siged-test", Key="originals/x/y")["Body"].read()
        assert raw.startswith(b"SGED1\n") and b"Objet S3" not in raw  # chiffré côté application
        assert b"".join(st.iter_plain("originals/x/y")) == data
        st.delete("originals/x/y")
        assert not st.exists("originals/x/y")
        storage.reset_storage()
