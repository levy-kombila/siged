# Numériser des documents papier

GEDarchive propose trois façons de faire entrer un document papier. Toutes aboutissent au même circuit : empreinte SHA-256, chiffrement AES-256, OCR (texte cherchable) et conversion PDF/A.

| Moyen | Pour qui | Matériel |
|---|---|---|
| **1. Téléphone, tablette ou webcam** (page *Numériser*) | Tout utilisateur qui dépose des documents | Aucun : l'appareil photo suffit |
| **2. Scanner ou copieur en réseau → dossier partagé** | Volumes importants, bureau équipé | Copieur avec fonction « numériser vers dossier » |
| **3. Scanner ou copieur → e-mail** | Copieurs qui savent seulement envoyer par e-mail | Boîte e-mail dédiée (IMAP) |

---

## 1. Avec le téléphone, une tablette ou une webcam

1. Menu **Numériser** (profils autorisés à déposer : contributeur, archiviste, administrateur).
2. **Photographier une page** ouvre l'appareil photo du téléphone. Sur PC, **Caméra en direct** utilise la webcam. **Importer des photos** reprend des photos déjà prises.
3. GEDarchive **détecte les bords de la feuille**. Faites glisser un coin pour l'ajuster, ou utilisez **Page entière**, **Pivoter** et **Placer avant / après** pour remettre les pages dans l'ordre.
4. Choisissez le **rendu** :
   * **Document** : fond blanc, ombres effacées, texte net. C'est le meilleur choix pour le texte et l'OCR.
   * **Niveaux de gris** : documents avec des nuances (plans, photocopies anciennes).
   * **Couleur** : tampons, signatures en couleur, photos.
5. Remplissez la fiche puis **Créer le document**. Les pages sont assemblées en **un seul PDF**.

**Passer du PC au téléphone** : la page *Numériser* affiche sur PC un **QR code**. Visez-le avec l'appareil photo du téléphone pour ouvrir la page, puis connectez-vous.
Le téléphone doit pouvoir joindre le site : utilisez l'adresse publique du tunnel ([mise_en_ligne_pc.md](mise_en_ligne_pc.md)) ou celle du serveur. L'adresse `https://localhost` n'existe que sur le PC.

**Conseils de prise de vue** : feuille à plat sur un fond plus sombre (bureau, dossier foncé), bonne lumière, sans contre-jour, téléphone parallèle à la feuille. Le flash crée souvent un reflet : évitez-le si la pièce est assez éclairée.

**Ce qui est conservé** : le PDF assemblé est l'original archivé. Le journal d'audit (action `SCAN_CAPTURE`) garde l'empreinte SHA-256 de chaque photo envoyée, le nombre de pages et le rendu choisi.

**Limites** : 60 pages et 25 Mo par photo. Les photos sont réduites dans le navigateur avant l'envoi (environ 1 Mo par page), ce qui reste compatible avec la limite de 100 Mo par envoi du tunnel Cloudflare. La **caméra en direct** demande une connexion HTTPS (`https://localhost`, le tunnel ou le serveur). Le bouton **Photographier une page** fonctionne partout.

**API** : `POST /api/scan` (champs `pages`, `metadata`, `options`) ; `GET /api/scan/qr?url=` renvoie le QR code en SVG. Détail dans `/docs`.

---

## 2. Scanner ou copieur en réseau → dossier partagé

Le worker capture chaque minute les fichiers déposés dans le **dossier surveillé** (`SIGED_INBOX_PATH`), avec le classement automatique par sous-dossier (`inbox/FIN.01/…`) et une fiche facultative `fichier.pdf.json`. Voir l'en-tête de `backend/app/jobs/hot_folder.py`.

Dans `docker-compose.yml`, ce dossier est un volume Docker (`inbox`), donc invisible pour un copieur. Pour qu'un copieur y écrive depuis un PC Windows :

1. Créez le dossier `D:\GEDarchive\inbox` et partagez-le sur le réseau (*Propriétés → Partage*), avec un compte réservé au copieur.
2. Dans `docker-compose.yml`, bloc `x-app`, remplacez `- inbox:/data/inbox` par `- D:/GEDarchive/inbox:/data/inbox`, puis `docker compose up -d`.
3. Sur le copieur, configurez « Numériser vers dossier (SMB) » : `\\NOM-DU-PC\inbox`, au format **PDF** de préférence.

Sur un serveur Linux, montez de la même façon un dossier partagé Samba à la place du volume.

---

## 3. Scanner ou copieur → e-mail

Si le copieur ne sait qu'envoyer par e-mail, réglez-le pour qu'il écrive à une boîte dédiée, puis renseignez `SIGED_IMAP_HOST`, `SIGED_IMAP_USER` et `SIGED_IMAP_PASSWORD` dans `.env` ([guide_secrets.md](guide_secrets.md), §6). Chaque pièce jointe devient un document, relevé toutes les 5 minutes.
