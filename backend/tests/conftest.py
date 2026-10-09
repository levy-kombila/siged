"""Fixtures communes. Base de test : SQLite par défaut, ou PostgreSQL via
SIGED_TEST_DATABASE_URL=postgresql+psycopg://user:pwd@host:port/base"""
import io
import json
import os
import tempfile
from datetime import date
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="siged-tests-"))
os.environ.update({
    "SIGED_ENVIRONMENT": "test",
    "SIGED_DATABASE_URL": os.environ.get("SIGED_TEST_DATABASE_URL", f"sqlite:///{_TMP}/test.db"),
    "SIGED_STORAGE_LOCAL_PATH": str(_TMP / "storage"),
    "SIGED_INBOX_PATH": str(_TMP / "inbox"),
    "SIGED_ENABLE_CONVERSION": "false",
    "SIGED_SECRET_KEY": "test-secret-key-for-pytest-only-0123456789",
})

from fastapi.testclient import TestClient  # noqa: E402

from app.core import config  # noqa: E402

config.get_settings.cache_clear()

from app.core.database import Base, SessionLocal, create_schema, init_engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services import events  # noqa: E402
from app.services.bootstrap import seed  # noqa: E402
from app.services.storage import reset_storage  # noqa: E402

ADMIN = ("admin", "Admin@SIGED2026")
PASSWORD = "Motdepasse#2026"


@pytest.fixture()
def settings():
    return config.get_settings()


@pytest.fixture()
def client():
    engine = init_engine()
    Base.metadata.drop_all(engine)
    create_schema()
    reset_storage()
    with SessionLocal() as db:
        seed(db)
    with TestClient(app) as c:
        yield c
    events._sender_override = None


@pytest.fixture()
def db(client):
    s = SessionLocal()
    yield s
    s.close()


def login(client, username, password):
    r = client.post("/api/auth/login", data={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def admin(client):
    return login(client, *ADMIN)


@pytest.fixture()
def make_user(client, admin):
    def _make(username, role):
        r = client.post("/api/users", headers=admin, json={
            "username": username, "email": f"{username}@test.ga", "password": PASSWORD, "role": role})
        assert r.status_code == 201, r.text
        return login(client, username, PASSWORD)
    return _make


# ------------------------------------------------------------------ Fichiers d'exemple
def make_pdf(text: str) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    y = 800
    for line in text.split("\n"):
        c.drawString(50, y, line)
        y -= 18
    c.save()
    return buf.getvalue()


def make_text_image(text: str) -> bytes:
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (1400, 200), "white")
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 64)
    except OSError:
        font = ImageFont.load_default(size=64)
    d.text((40, 60), text, fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def meta(**over):
    m = {"title": "Facture fournisseur SEEG mars", "author": "Service comptable",
         "document_date": date(2025, 3, 15).isoformat(), "doc_type": "facture",
         "keywords": ["facture", "fournisseur"], "dua_years": 10, "final_disposition": "DESTROY"}
    m.update(over)
    return m


def upload(client, headers, content: bytes = None, filename="doc.pdf", ctype="application/pdf", **over):
    content = content if content is not None else make_pdf(f"Document {over}")
    return client.post("/api/documents", headers=headers,
                       files={"file": (filename, content, ctype)},
                       data={"metadata": json.dumps(meta(**over))})
