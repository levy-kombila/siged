"""Sprint 9 — Numérisation par téléphone / webcam : photos -> PDF redressé et amélioré."""
import io
import json

import pytest
from PIL import Image, ImageDraw
from pypdf import PdfReader

from app.services import scan
from app.services.documents import BusinessError
from tests.conftest import meta

W, H = 1200, 900
QUAD = [(240, 120), (1000, 170), (960, 820), (180, 780)]


def photo(color=(70, 55, 40), fmt="JPEG") -> bytes:
    img = Image.new("RGB", (W, H), color)
    d = ImageDraw.Draw(img)
    d.polygon(QUAD, fill=(230, 228, 218))
    d.rectangle((400, 350, 800, 380), fill=(20, 20, 20))
    buf = io.BytesIO()
    img.save(buf, fmt)
    return buf.getvalue()


def corners():
    return [[x / W, y / H] for x, y in QUAD]


def post_scan(client, headers, pages, options=None, **over):
    return client.post("/api/scan", headers=headers,
                       files=[("pages", (f"p{i}.jpg", b, "image/jpeg")) for i, b in enumerate(pages)],
                       data={"metadata": json.dumps(meta(title="Facture numérisée", **over)),
                             "options": json.dumps(options or {})})


def test_scan_creates_multipage_pdf_document(client, admin):
    r = post_scan(client, admin, [photo(), photo((90, 90, 90))],
                  {"mode": "document", "pages": [{"corners": corners(), "rotation": 0}, {"corners": None, "rotation": 90}]})
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["source"] == "scan" and d["current_version"]["mime_type"] == "application/pdf"
    pdf = client.get(f"/api/documents/{d['id']}/download", headers=admin).content
    pages = PdfReader(io.BytesIO(pdf)).pages
    assert len(pages) == 2
    # page 2 tournée de 90° : portrait (plus haute que large)
    assert float(pages[1].mediabox.height) > float(pages[1].mediabox.width)
    log = next(e for e in client.get(f"/api/documents/{d['id']}/audit", headers=admin).json() if e["action"] == "SCAN_CAPTURE")
    assert log["details"]["pages"] == 2 and len(log["details"]["page_sha256"]) == 2


def test_perspective_correction_keeps_only_the_sheet():
    img = scan.process_page(photo(), scan.PageOptions(corners(), 0), "gris")
    # Taille ≈ côtés de la feuille, et plus de fond sombre dans les coins
    assert 700 < img.width < 800 and 620 < img.height < 680
    assert min(img.getpixel((5, 5)), img.getpixel((img.width - 6, img.height - 6))) > 200


def test_document_mode_whitens_background():
    img = scan.process_page(photo(), scan.PageOptions(corners(), 0), "document")
    assert img.mode == "L" and img.getpixel((30, 30)) == 255
    assert scan.process_page(photo(), scan.PageOptions(), "couleur").mode == "RGB"


@pytest.mark.parametrize("bad", [
    [[0, 0], [1, 0], [1, 1]],                       # 3 points
    [[0, 0], [1, 1], [1, 0], [0, 1]],               # forme croisée
    [[0, 0], [0.5, 0.5], [1, 1], [0, 1]],           # points alignés
])
def test_invalid_corners_rejected(bad):
    with pytest.raises(BusinessError):
        scan.process_page(photo(), scan.PageOptions(bad, 0), "document")


def test_scan_errors_and_permissions(client, admin, make_user):
    assert post_scan(client, admin, [b"pas une image"]).status_code == 422
    assert post_scan(client, admin, [photo()], {"mode": "sepia"}).status_code == 422
    assert post_scan(client, admin, [photo()], {"pages": [{"rotation": 45}]}).status_code == 422
    r = client.post("/api/scan", headers=admin, files=[("pages", ("p.jpg", photo(), "image/jpeg"))],
                    data={"metadata": json.dumps(meta()), "options": "{pas du json"})
    assert r.status_code == 422
    lecteur = make_user("lect9", "lecteur")
    assert post_scan(client, lecteur, [photo()]).status_code == 403


def test_scan_png_and_too_many_pages(client, admin, monkeypatch):
    assert post_scan(client, admin, [photo(fmt="PNG")]).status_code == 201
    monkeypatch.setattr(scan, "MAX_PAGES", 2)
    assert post_scan(client, admin, [photo()] * 3).status_code == 422


def test_qr_code(client, admin):
    r = client.get("/api/scan/qr", headers=admin, params={"url": "https://demo.trycloudflare.com/#scan"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml") and b"<svg" in r.content
    assert client.get("/api/scan/qr", headers=admin, params={"url": "javascript:alert(1)"}).status_code == 422
    assert client.get("/api/scan/qr", params={"url": "https://x.ga"}).status_code == 401
