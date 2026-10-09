"""Sprint 3 — Plan de classement, classement automatique, import par lot, hot folder, messagerie."""
import io
import json
import zipfile
from email.message import EmailMessage

from app.jobs import hot_folder, mail_ingest
from tests.conftest import make_pdf, upload


def test_default_plan_tree(client, admin):
    tree = client.get("/api/classification", headers=admin).json()
    codes = {n["code"] for n in tree}
    assert {"ADM", "RH", "FIN", "JUR"} <= codes
    fin = next(n for n in tree if n["code"] == "FIN")
    assert {c["code"] for c in fin["children"]} == {"FIN.01", "FIN.02"}


def test_auto_classification_on_upload(client, admin):
    r = upload(client, admin, doc_type="facture", keywords=["facture"])
    assert r.json()["classification"]["code"] == "FIN.01"
    r = upload(client, admin, doc_type="contrat", keywords=["contrat de travail"], title="Contrat de M. Obiang")
    assert r.json()["classification"]["code"] == "RH.01"


def test_manual_classification_wins(client, admin):
    r = upload(client, admin, doc_type="facture", classification_code="JUR.01")
    assert r.json()["classification"]["code"] == "JUR.01"


def test_suggest_endpoint(client, admin):
    r = client.post("/api/classification/suggest", headers=admin,
                    json={"doc_type": "pv", "keywords": ["réunion"], "title": "PV du conseil"})
    assert r.json()["code"] == "ADM.02"


def test_manage_plan_and_cycles(client, admin, make_user):
    r = client.post("/api/classification", headers=admin, json={
        "code": "INF", "label": "Informatique", "default_dua_years": 5, "default_final_disposition": "DESTROY"})
    assert r.status_code == 201
    inf = r.json()["id"]
    r = client.post("/api/classification", headers=admin, json={"code": "INF.01", "label": "Projets", "parent_id": inf})
    child = r.json()["id"]
    # cycle interdit
    r = client.put(f"/api/classification/{inf}", headers=admin, json={"code": "INF", "label": "Informatique",
                                                                         "parent_id": child})
    assert r.status_code == 422
    # rubrique non vide
    assert client.delete(f"/api/classification/{inf}", headers=admin).status_code == 409
    assert client.delete(f"/api/classification/{child}", headers=admin).status_code == 204
    # un contributeur ne gère pas le plan
    contrib = make_user("contrib2", "contributeur")
    assert client.post("/api/classification", headers=contrib, json={"code": "X", "label": "X"}).status_code == 403


def test_batch_upload_multiple_files(client, admin):
    common = {"author": "Scan RH", "document_date": "2024-01-10", "doc_type": "bulletin-paie",
              "keywords": ["paie"], "dua_years": 10, "final_disposition": "DESTROY"}
    files = [("files", (f"bulletin_{i}.pdf", make_pdf(f"Bulletin {i}"), "application/pdf")) for i in range(3)]
    files.append(("files", ("vide.pdf", b"", "application/pdf")))
    r = client.post("/api/documents/batch", headers=admin, files=files, data={"metadata": json.dumps(common)})
    assert r.status_code == 207
    body = r.json()
    assert len(body["created"]) == 3
    assert body["errors"][0]["file"] == "vide.pdf"
    assert body["created"][0]["title"] == "bulletin_0"
    assert body["created"][0]["source"] == "batch"


def test_batch_zip_with_manifest(client, admin):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("manifest.csv", "filename;title;author;document_date;doc_type;keywords;dua_years;final_disposition;classification_code\n"
                                   "a.pdf;Convention ARTF;DAJ;2023-05-02;convention;convention;30;ARCHIVE;JUR.01\n"
                                   "b.pdf;Budget 2024;DAF;2024-01-01;budget;budget;10;ARCHIVE;\n")
        z.writestr("a.pdf", make_pdf("Convention"))
        z.writestr("b.pdf", make_pdf("Budget"))
    r = client.post("/api/documents/batch", headers=admin, files=[("files", ("lot.zip", buf.getvalue(), "application/zip"))])
    body = r.json()
    assert not body["errors"], body["errors"]
    titles = {d["title"]: d for d in body["created"]}
    assert titles["Convention ARTF"]["classification"]["code"] == "JUR.01"
    assert titles["Budget 2024"]["classification"]["code"] == "FIN.02"


def test_hot_folder_capture(client, admin, settings):
    inbox = settings.inbox_path
    (inbox / "FIN.01").mkdir(parents=True, exist_ok=True)
    (inbox / "FIN.01" / "facture_0042.pdf").write_bytes(make_pdf("Facture 0042"))
    (inbox / "courrier_ministere.pdf").write_bytes(make_pdf("Courrier"))
    (inbox / "courrier_ministere.pdf.json").write_text(json.dumps({
        "title": "Courrier du ministère", "author": "Ministère", "doc_type": "courrier",
        "keywords": ["courrier"], "dua_years": 5, "final_disposition": "DESTROY"}))
    (inbox / "corrompu.pdf").write_bytes(b"")
    res = hot_folder.scan(inbox, min_age=0)
    assert len(res["processed"]) == 2
    assert len(res["errors"]) == 1
    assert list((inbox / "_errors").glob("*.error.txt"))
    docs = client.get("/api/search", headers=admin).json()["items"]
    by_title = {d["title"]: d for d in docs}
    assert by_title["facture 0042"]["classification"]["code"] == "FIN.01"
    assert by_title["Courrier du ministère"]["source"] == "hotfolder"


def test_mail_ingestion(client, admin):
    msg = EmailMessage()
    msg["From"] = "Direction RH <drh@artf.ga>"
    msg["To"] = "ged@artf.ga"
    msg["Subject"] = "Note de service n°12"
    msg["Date"] = "Mon, 06 Oct 2026 09:00:00 +0100"
    msg.set_content("Veuillez trouver la note en pièce jointe.")
    msg.add_attachment(make_pdf("Note de service"), maintype="application", subtype="pdf", filename="note12.pdf")
    refs = mail_ingest.ingest_message(msg.as_bytes())
    assert len(refs) == 1
    d = client.get(f"/api/search?reference={refs[0]}", headers=admin).json()["items"][0]
    assert d["author"] == "Direction RH" and d["source"] == "email"
    assert d["extra"]["email_from"] == "drh@artf.ga"
    assert d["document_date"] == "2026-10-06"
