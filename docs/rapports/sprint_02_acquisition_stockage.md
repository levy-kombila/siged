# Sprint 2 — Acquisition, empreinte SHA-256 et stockage hybride chiffré

**Période** : semaines 5 et 6 · **Exigences** : EX-01, EX-05 (manuel), EX-07, EX-13, EX-14, EX-16 (au repos)
**Vélocité** : 26 points engagés / 26 livrés

## 1. Objectif du sprint

Déposer un document avec sa fiche de métadonnées obligatoire, prouver son intégrité dès la réception et le stocker chiffré, séparément de la base.

## 2. Récits utilisateurs

| ID | Récit | Points | Statut |
|---|---|---|---|
| US-2.1 | En tant que contributeur, je téléverse un fichier avec sa fiche (titre, auteur, date, type, mots-clés, DUA) | 5 | ✔ |
| US-2.2 | En tant qu'archiviste, je veux qu'aucun document ne puisse être déposé sans fiche complète | 2 | ✔ |
| US-2.3 | En tant qu'auditeur, je veux l'empreinte SHA-256 de chaque fichier calculée au dépôt | 3 | ✔ |
| US-2.4 | En tant que RSSI, je veux les fichiers chiffrés en AES-256 et hors de la base | 8 | ✔ |
| US-2.5 | En tant que gestionnaire, je veux être averti si le fichier existe déjà (doublon) | 3 | ✔ |
| US-2.6 | En tant que métier, je veux ajouter des métadonnées libres (n° facture, matricule) | 3 | ✔ |
| US-2.7 | En tant qu'archiviste, je veux une cote lisible unique (DOC-AAAA-NNNNNN) | 2 | ✔ |

## 3. Réalisation

* **Réception en flux** : lecture par blocs de 1 Mo, empreinte SHA-256 calculée à la volée (aucune relecture), taille maximale configurable (200 Mo), fichier vide refusé.
* **Détection du type** par signature binaire (`%PDF`, PNG, JPEG, TIFF) : un PDF nommé `image.png` est bien reconnu comme PDF.
* **Stockage hybride** : interface `StorageBackend` avec deux implémentations (`LocalBackend`, `S3Backend` pour MinIO/S3) ; la base ne contient que la clé `originals/{document}/{version}`.
* **Chiffrement** : façade `EncryptedStorage` en AES-256-GCM par blocs, nonce unique par bloc, données associées anti-troncature ; écriture atomique (fichier temporaire + renommage).
* **Doublons** : refus 409 avec la cote du document existant, forçage possible (`allow_duplicate=true`).
* **Métadonnées** : validation Pydantic ; DUA et sort final héritables de la rubrique de classement, sinon dépôt refusé.
* **Transaction unique** : fiche + version 1.0 + entrée d'audit `DOCUMENT_CREATE` (avec empreinte et taille).

## 4. Tests (10 tests — `tests/test_sprint2_acquisition.py`)

Création v1.0 avec empreinte et date de fin de DUA exactes · chacun des champs obligatoires manquant → 422 · mots-clés vides → 422 · héritage de la DUA depuis la rubrique `RH.02` · refus sans DUA ni rubrique · doublon refusé puis forcé · **aucune donnée en clair sur le disque** (recherche d'une chaîne secrète dans les fichiers stockés) · base sans binaire · métadonnées dynamiques · aller-retour de chiffrement sur 3 Mo + détection d'un octet altéré + détection d'une troncature · détection MIME malgré une extension mensongère.

**Résultat : 10/10 ✔**

## 5. Rétrospective

* **Positif** : le chiffrement par blocs permet de déchiffrer en flux (aperçu, téléchargement) sans charger le fichier en mémoire.
* **Point d'attention** : la clé AES devient un actif critique → démarrage refusé en production sans clé explicite ; procédure de séquestre ajoutée au cahier d'architecture.
