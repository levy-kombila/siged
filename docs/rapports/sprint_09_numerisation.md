# Sprint 9 — Numérisation par téléphone et webcam

## Besoin du client
Numériser les documents papier sans scanner : avec un téléphone, une tablette ou la webcam du PC.

## Solution retenue
Le navigateur sert de scanner : pas d'application à installer, et tout appareil avec un navigateur convient.

| Étape | Où | Détail |
|---|---|---|
| Prise de vue | Navigateur | Appareil photo natif (`capture="environment"`), caméra en direct (`getUserMedia`, HTTPS) ou import de photos |
| Préparation | Navigateur | Orientation appliquée, réduction à 2400 px (environ 1 Mo par page), détection de la feuille (seuil d'Otsu + plus grande zone claire, coins extrêmes) |
| Ajustement | Navigateur | Coins déplaçables (souris ou doigt), rotation, ordre des pages, suppression |
| Redressement | Serveur | Transformation de perspective (Pillow, système 8×8 résolu sans dépendance), rognage du liseré |
| Amélioration | Serveur | *Document* : fond estimé par flou large puis retiré (ombres effacées), contraste renforcé ; *Gris* ; *Couleur* |
| Assemblage | Serveur | PDF multipage dimensionné au format A4, puis circuit normal : SHA-256, chiffrement, OCR, PDF/A |

Le traitement d'image est fait côté serveur (Pillow, déjà utilisé) pour un résultat identique sur tous les appareils et des tests automatisés. Le navigateur ne fait que la détection, légère et instantanée.

## Ajouts
* `POST /api/scan` (permission `document:write`) et `GET /api/scan/qr` (QR code SVG, bibliothèque `segno`, pur Python).
* Vue *Numériser* (menu), lien depuis *Déposer*, QR code « Continuer sur le téléphone » sur PC.
* Traçabilité : action d'audit `SCAN_CAPTURE` avec l'empreinte de chaque photo d'origine.
* En-tête `Permissions-Policy: camera=(self), microphone=(), geolocation=()` (API et Caddy).
* Guide `docs/numerisation.md` : téléphone et webcam, copieur vers dossier partagé, copieur vers e-mail.

## Tests
`tests/test_sprint9_numerisation.py` : 9 tests (PDF multipage, rotation, redressement, fond blanchi, coins invalides, erreurs, droits, PNG, nombre de pages, QR code). Parcours vérifié dans un navigateur sans interface : détection automatique, coin déplacé, caméra simulée, document de 3 pages créé et classé automatiquement.
