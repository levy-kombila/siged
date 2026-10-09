# Rapport final — Bilan du projet et recette

## 1. Synthèse

SIGED couvre les **20 exigences** du cahier des charges. Le projet a été conduit en 8 sprints (cadrage + 7 sprints de réalisation) pour **199 points** livrés sur 199 engagés.

| Indicateur | Valeur |
|---|---|
| Code applicatif Python | ≈ 3 500 lignes (hors tests) |
| Interface web | 3 fichiers (HTML, CSS, JavaScript natif) |
| Opérations d'API documentées (OpenAPI) | 48 |
| Tables | 11 |
| Tests automatisés | 71 (SQLite : 70 réussis, 1 propre à PostgreSQL ignoré ; PostgreSQL : 70 réussis, 1 propre à SQLite ignoré) |
| Recherche plein texte sur 2 000 notices | 0,44 s (PostgreSQL) — objectif < 2 s |

## 2. Matrice de conformité

| Réf. | Exigence | Réalisation | Preuve (tests) | Statut |
|---|---|---|---|---|
| EX-01 | Centralisation, pas de doublons | Référentiel unique, refus des doublons par empreinte | `test_duplicate_detection` | ✔ |
| EX-02 | Recherche par métadonnées | 13 critères, index B-tree / trigrammes | `test_metadata_criteria`, `test_search_dynamic_metadata` | ✔ |
| EX-03 | Sécurité et traçabilité | JWT, RBAC, journal chaîné | sprints 1 et 6 | ✔ |
| EX-04 | Interopérabilité ERP/SIRH/messagerie | API + clés, webhooks HMAC, IMAP, SMTP, OpenAPI | `test_api_key_for_erp`, `test_webhooks_signed`, `test_mail_ingestion`, `test_openapi_contract` | ✔ |
| EX-05 | Manuel, lot, capture auto | Dépôt, lot/ZIP + manifeste, dossier partagé, API | `test_batch_*`, `test_hot_folder_capture` | ✔ |
| EX-06 | PDF/A + OCR | OCRmyPDF, Tesseract, LibreOffice → PDF/A-2b | `test_pdf_converted_to_pdfa`, `test_scanned_image_ocr_is_searchable`, `test_docx_converted_to_pdfa` | ✔ |
| EX-07 | Fiche de métadonnées obligatoire | Validation stricte, héritage DUA de la rubrique | `test_mandatory_metadata`, `test_dua_*` | ✔ |
| EX-08 | Plan de classement, auto/manuel | Arborescence + règles explicables | `test_auto_classification_on_upload`, `test_manual_classification_wins` | ✔ |
| EX-09 | Recherche multicritère + plein texte | FTS français, extraits surlignés | `test_fulltext_search_finds_content` | ✔ |
| EX-10 | Prévisualisation sans téléchargement | Pages rendues en PNG + PDF inline | `test_preview_inline_without_download`, `test_preview_as_page_images` | ✔ |
| EX-11 | Versions sans écraser l'historique | Majeure/mineure, historique immuable | `test_minor_and_major_versions_keep_history` | ✔ |
| EX-12 | Workflow brouillon/validation/validé | Machine à états, séparation des tâches | `test_full_workflow`, `test_author_cannot_self_validate` | ✔ |
| EX-13 | Stockage hybride | PostgreSQL + MinIO/S3 ou disque | `test_metadata_stored_separately_from_file` | ✔ |
| EX-14 | SHA-256 au dépôt, non-altération | Empreinte en flux + contrôle nocturne | `test_upload_creates_document_v1`, `test_integrity_check_detects_tampering` | ✔ |
| EX-15 | RBAC | 5 rôles, 10 permissions | `test_rbac_*` | ✔ |
| EX-16 | TLS 1.3 + AES-256 | Nginx TLS 1.3 only ; AES-256-GCM applicatif | `test_files_are_encrypted_at_rest`, `test_crypto_roundtrip_and_tamper_detection` ; configuration `deploy/nginx` | ✔ |
| EX-17 | ISO 15489 / ISO 14721 | Correspondances détaillées (cahier §9), export AIP BagIt | `test_aip_export_oais` | ✔ |
| EX-18 | DUA et sort final automatisés | Job quotidien, bordereau, élimination certifiée, versement, gel | `test_retention_*`, `test_legal_hold_blocks_disposal` | ✔ |
| EX-19 | Journal d'audit inaltérable | Chaîne SHA-256 + déclencheurs PostgreSQL | `test_audit_*`, `test_consultations_are_traced` | ✔ |
| EX-20 | < 2 s, 99,9 %, sauvegardes | Mesures automatisées ; architecture HA décrite ; sauvegarde quotidienne | `test_search_under_two_seconds_on_volume`, `test_health` | ✔ (HA : architecture cible, voir §4) |

## 3. Scénario de recette de bout en bout

1. L'administrateur crée les comptes `redacteur` (contributeur) et `valideur` (validateur).
2. Le rédacteur dépose une facture scannée (image) : cote attribuée, empreinte affichée, rubrique `FIN.01` attribuée automatiquement, DUA de 10 ans héritée.
3. Quelques secondes plus tard, la version est convertie en PDF/A-2b avec OCR ; la recherche « SEEG » la retrouve avec un extrait surligné.
4. Le rédacteur la soumet ; le valideur la rejette (« montant erroné ») ; le rédacteur dépose la v1.1 corrigée et la resoumet ; le valideur l'approuve : version figée, webhook envoyé au SIRH/ERP.
5. Un auditeur vérifie le journal (chaîne intègre) et lance un contrôle d'intégrité (0 anomalie).
6. Simulation d'altération d'un fichier sur le stockage → le contrôle signale l'anomalie et une alerte est émise.
7. À échéance de la DUA, l'archiviste consulte le bordereau, applique le sort final ; la facture est éliminée, sa notice et le certificat d'élimination restent consultables.

Le jeu de démonstration (`scripts/demo_data.py`) permet de rejouer ce scénario en quelques minutes.

## 4. Réserves et suite à donner

| Réserve | Nature | Proposition |
|---|---|---|
| Disponibilité 99,9 % | La composition livrée est mono-serveur ; l'objectif suppose la redondance | Déployer l'architecture cible (2 API, PostgreSQL répliqué avec bascule, MinIO distribué) décrite au cahier §10.2 |
| Volumétrie | Tests de charge réalisés sur 2 000 notices | Campagne sur un volume de production (≥ 100 000 documents) avant mise en service |
| Valeur probante renforcée | Horodatage interne | Horodatage qualifié RFC 3161 des empreintes |
| Annuaire | Comptes locaux | Connexion LDAP / Active Directory ou OpenID Connect |
| Migrations de schéma | `create_all` | Alembic avant la première mise à jour en production |

## 5. Bilan personnel

Le projet a mobilisé la conception de systèmes d'information (modélisation, architecture en couches), la sécurité (cryptographie appliquée, contrôle d'accès, analyse de menaces), l'administration de bases de données (index plein texte, déclencheurs, sauvegarde/restauration) et l'administration système (conteneurs, TLS, supervision). Les deux défauts découverts en recette — bifurcation du journal sous concurrence et aperçu PDF non universel — rappellent que les exigences non fonctionnelles se valident par des essais réalistes et non sur le papier.
