"""Sprint 4 — Conversion PDF/A, OCR, extraction de texte, recherche multicritère et plein texte."""
import io
import shutil

import pytest

from tests.conftest import make_pdf, make_text_image, upload

needs_ocrmypdf = pytest.mark.skipif(not (shutil.which("ocrmypdf") and shutil.which("gs")),
                                    reason="OCRmyPDF + Ghostscript requis")
needs_soffice = pytest.mark.skipif(not shutil.which("soffice"), reason="LibreOffice requis")
needs_tesseract = pytest.mark.skipif(not shutil.which("tesseract"), reason="Tesseract requis")


@pytest.fixture()
def conversion_on(settings):
    settings.enable_conversion = True
    yield
    settings.enable_conversion = False


def _detail(client, headers, doc_id):
    return client.get(f"/api/documents/{doc_id}", headers=headers).json()


def test_text_extraction_from_pdf(client, admin):
    r = upload(client, admin, make_pdf("Contrat de maintenance du serveur Libreville"))
    d = _detail(client, admin, r.json()["id"])
    assert d["current_version"]["conversion_status"] in ("PARTIAL", "DONE")


def test_fulltext_search_finds_content(client, admin):
    upload(client, admin, make_pdf("Rapport sur la fibre optique a Port-Gentil"), title="Rapport annuel")
    upload(client, admin, make_pdf("Note interne sans rapport"), title="Note")
    res = client.get("/api/search", params={"q": "Port-Gentil"}, headers=admin).json()
    assert res["total"] == 1
    assert res["items"][0]["title"] == "Rapport annuel"
    assert "<mark>" in (res["items"][0]["snippet"] or "")


def test_metadata_criteria(client, admin):
    upload(client, admin, title="Facture A", author="SEEG", doc_type="facture", document_date="2024-02-01")
    upload(client, admin, title="Facture B", author="Airtel", doc_type="facture", document_date="2025-06-01")
    upload(client, admin, title="PV conseil", author="DG", doc_type="pv", keywords=["réunion"],
           document_date="2025-01-15", dua_years=10, final_disposition="ARCHIVE")
    s = lambda **p: client.get("/api/search", params=p, headers=admin).json()  # noqa: E731
    assert s(doc_type="facture")["total"] == 2
    assert s(author="airtel")["total"] == 1
    assert s(date_from="2025-01-01")["total"] == 2
    assert s(date_from="2025-01-01", doc_type="facture")["items"][0]["title"] == "Facture B"
    assert s(keyword="réunion")["total"] == 1
    assert s(title="facture", sort="title")["items"][0]["title"] == "Facture A"


def test_search_by_classification_includes_children(client, admin):
    upload(client, admin, doc_type="facture", keywords=["facture"])
    upload(client, admin, doc_type="budget", keywords=["budget"], title="Budget")
    fin = next(n for n in client.get("/api/classification/flat", headers=admin).json() if n["code"] == "FIN")
    assert client.get("/api/search", params={"classification_id": fin["id"]}, headers=admin).json()["total"] == 2


def test_search_dynamic_metadata(client, admin):
    upload(client, admin, extra_metadata={"matricule": "AG-1234"})
    upload(client, admin, extra_metadata={"matricule": "AG-9999"})
    r = client.get("/api/search", params={"meta_key": "matricule", "meta_value": "1234"}, headers=admin).json()
    assert r["total"] == 1


def test_pagination(client, admin):
    for i in range(5):
        upload(client, admin, title=f"Doc {i}")
    r = client.get("/api/search", params={"size": 2, "page": 3, "sort": "title"}, headers=admin).json()
    assert r["total"] == 5 and len(r["items"]) == 1


@needs_ocrmypdf
@pytest.mark.slow
def test_pdf_converted_to_pdfa(client, admin, conversion_on):
    r = upload(client, admin, make_pdf("Arrete ministeriel numero 12"))
    v = _detail(client, admin, r.json()["id"])["current_version"]
    assert v["conversion_status"] == "DONE"
    assert v["archival_format"] == "PDF/A-2b"
    assert v["archival_sha256"] and v["archival_sha256"] != v["sha256"]


@needs_ocrmypdf
@needs_tesseract
@pytest.mark.slow
def test_scanned_image_ocr_is_searchable(client, admin, conversion_on):
    r = upload(client, admin, make_text_image("Attestation de stage ARTF"), filename="scan.png",
               ctype="image/png", title="Scan attestation")
    v = _detail(client, admin, r.json()["id"])["current_version"]
    assert v["ocr_applied"] is True
    assert v["archival_format"] == "PDF/A-2b"
    res = client.get("/api/search", params={"q": "Attestation"}, headers=admin).json()
    assert res["total"] == 1


@needs_soffice
@pytest.mark.slow
def test_docx_converted_to_pdfa(client, admin, conversion_on):
    import docx
    d = docx.Document()
    d.add_paragraph("Procès-verbal de la réunion du comité de direction")
    buf = io.BytesIO()
    d.save(buf)
    r = upload(client, admin, buf.getvalue(), filename="pv.docx",
               ctype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
               doc_type="pv", title="PV CODIR")
    v = _detail(client, admin, r.json()["id"])["current_version"]
    assert v["archival_format"] == "PDF/A-2b", v
    assert client.get("/api/search", params={"q": "comité"}, headers=admin).json()["total"] == 1
