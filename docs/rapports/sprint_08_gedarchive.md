# Sprint 8 — GEDarchive : identité, rayonnage, alertes d'obsolescence

## Objectifs (demande du client)
1. Renommer l'application **GEDarchive**.
2. Thème **rose et bleu**, présentation améliorée.
3. **Rayonnage** : savoir où se trouve chaque exemplaire papier.
4. **Notifications** : prévenir avant qu'un document ne devienne obsolète.

## Réalisé
* **Identité** : nom affiché, titre de l'API, e-mails `[GEDarchive]`, favicon. Les variables `SIGED_*`, les en-têtes `X-SIGED-*` des webhooks et les noms internes sont inchangés : aucun `.env` ni aucune intégration existante n'est à modifier.
* **Interface** : navigation bleu encre avec repère rose, barre supérieure avec cloche, tableau de bord (bande d'indicateurs, échéances sous 30 jours), cotes présentées comme des étiquettes de boîte, page de connexion repensée, affichage mobile.
* **Rayonnage** : table `shelf_locations` hiérarchique (site, salle, rayonnage, travée, tablette, boîte), capacité, contrôle de cohérence des niveaux et des cycles, refus de supprimer un emplacement non vide. Les boîtes sont dessinées posées sur leur tablette avec leur taux de remplissage. Rangement depuis la fiche document (`PUT /api/documents/{id}/location`), tracé dans le journal d'audit. Nouvelle permission `shelving:manage` (admin, archiviste).
* **Obsolescence** : champ `valid_until` (fin de validité) sur le document ; service `obsolescence` qui surveille la fin de validité et la fin de DUA (sauf gel juridique) ; notifications par palier J-90, J-30, J-7, échu, sans doublon, adressées au déposant et aux profils `retention:manage`, avec e-mail récapitulatif si SMTP est configuré. Tâche planifiée chaque matin à 07:00 (worker) et dans `/api/cron/daily`. Vue *Échéances* et bouton d'envoi immédiat.

## API ajoutée
`/api/shelving` (arbre, `flat`, `kinds`, CRUD, `/{id}/documents`), `PUT /api/documents/{id}/location`, `/api/notifications` (liste, `/{id}/read`, `/read-all`, `/run`), `GET /api/obsolescence/upcoming?days=`.

## Base de données
Nouvelles tables créées automatiquement. Sur une base existante, `sql/postgres_init.sql` ajoute les colonnes `valid_until`, `shelf_location_id` et `physical_ref` (`ADD COLUMN IF NOT EXISTS`, idempotent). Aucune migration manuelle.

## Tests
`tests/test_sprint8_gedarchive.py` : 8 tests (rayonnage, capacité, droits, paliers, idempotence, gel juridique, lecture des notifications, statistiques). Suite complète : 84 réussis, 4 ignorés (tests propres à PostgreSQL ou à l'OCR).
