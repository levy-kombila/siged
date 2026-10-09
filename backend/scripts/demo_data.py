"""Jeu de données de démonstration : utilisateurs par rôle + documents d'exemple.

    python -m scripts.demo_data            (API démarrée sur http://localhost:8000)
    python -m scripts.demo_data --url https://siged.local --insecure
"""
import argparse
import io
import json
from datetime import date

import httpx

USERS = [("archiviste", "archiviste"), ("valideur", "validateur"), ("redacteur", "contributeur"), ("consultant", "lecteur")]
PASSWORD = "Demo#SIGED2026"


def pdf(lines: list[str]) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(60, 790, lines[0])
    c.setFont("Helvetica", 11)
    for i, line in enumerate(lines[1:]):
        c.drawString(60, 760 - i * 16, line)
    c.save()
    return buf.getvalue()


DOCS = [
    dict(title="Facture SEEG - électricité mars 2025", author="SEEG", document_date="2025-03-31", doc_type="facture",
         keywords=["facture", "fournisseur", "électricité"], extra_metadata={"numero_facture": "SEEG-25-0331"},
         body=["FACTURE N° SEEG-25-0331", "Fournisseur : Société d'Énergie et d'Eau du Gabon",
               "Consommation électrique du siège - Libreville", "Montant TTC : 1 245 000 FCFA"]),
    dict(title="Contrat de travail - Agent comptable", author="Direction des Ressources Humaines",
         document_date="2024-09-01", doc_type="contrat", keywords=["contrat de travail", "embauche"],
         extra_metadata={"matricule": "AG-2024-117"},
         body=["CONTRAT DE TRAVAIL A DUREE INDETERMINEE", "Entre l'établissement et M. Mba Ondo",
               "Poste : agent comptable - Matricule AG-2024-117", "Prise de fonction : 1er septembre 2024"]),
    dict(title="PV du comité de direction du 12 janvier 2026", author="Secrétariat général",
         document_date="2026-01-12", doc_type="pv", keywords=["procès-verbal", "réunion"],
         body=["PROCES-VERBAL DU COMITE DE DIRECTION", "Ordre du jour : budget 2026, schéma directeur informatique",
               "Décision : lancement du projet de gestion électronique des documents"]),
    dict(title="Budget primitif 2026", author="Direction financière", document_date="2025-12-15", doc_type="budget",
         keywords=["budget", "loi de finances"],
         body=["BUDGET PRIMITIF 2026", "Fonctionnement : 2,4 milliards FCFA", "Investissement : 900 millions FCFA"]),
    dict(title="Courrier au Ministère de l'Économie (2014)", author="Direction générale", document_date="2014-05-20",
         doc_type="courrier", keywords=["courrier", "correspondance"], dua_years=5, final_disposition="DESTROY",
         body=["Objet : transmission du rapport d'activité 2013", "Monsieur le Ministre,",
               "J'ai l'honneur de vous transmettre le rapport d'activité de l'exercice 2013."]),
    dict(title="Convention de partenariat ARTF (2003)", author="Direction juridique", document_date="2003-02-10",
         doc_type="convention", keywords=["convention"], dua_years=20, final_disposition="ARCHIVE",
         body=["CONVENTION DE PARTENARIAT", "Durée : 5 ans renouvelables", "Objet : échange de données techniques"]),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--admin", default="admin")
    ap.add_argument("--password", default="Admin@SIGED2026")
    ap.add_argument("--insecure", action="store_true")
    a = ap.parse_args()
    c = httpx.Client(base_url=a.url, verify=not a.insecure, timeout=120)

    def token(u, p):
        r = c.post("/api/auth/login", data={"username": u, "password": p})
        r.raise_for_status()
        return {"Authorization": "Bearer " + r.json()["access_token"]}

    admin = token(a.admin, a.password)
    for username, role in USERS:
        c.post("/api/users", headers=admin, json={"username": username, "email": f"{username}@siged.ga",
                                                  "full_name": username.capitalize(), "password": PASSWORD, "role": role})
    redac, valid = token("redacteur", PASSWORD), token("valideur", PASSWORD)
    for d in DOCS:
        body = d.pop("body")
        r = c.post("/api/documents", headers=redac, files={"file": (d["title"][:40] + ".pdf", pdf(body), "application/pdf")},
                   data={"metadata": json.dumps(d)})
        if r.status_code != 201:
            print("!", d["title"], r.text)
            continue
        doc = r.json()
        print("+", doc["reference"], doc["title"], "->", (doc["classification"] or {}).get("code"))
        if doc["doc_type"] != "pv":
            c.post(f"/api/documents/{doc['id']}/submit", headers=redac)
            if doc["doc_type"] != "budget":
                c.post(f"/api/documents/{doc['id']}/approve", headers=valid, json={"comment": "Conforme"})
    print(f"Comptes de démonstration (mot de passe {PASSWORD}) : {[u for u, _ in USERS]}  — {date.today()}")


if __name__ == "__main__":
    main()
