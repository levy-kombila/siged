# Mettre GEDarchive en ligne depuis votre PC (démonstration gratuite, sans compte, sans carte)

SIGED tourne déjà sur votre PC avec Docker (https://localhost). Un **tunnel Cloudflare** rend cette même application accessible depuis Internet, sur une adresse sécurisée du type :

```
https://mots-aleatoires-1234.trycloudflare.com
```

| | |
|---|---|
| Coût | Gratuit |
| Compte / carte bancaire | Aucun |
| Fonctionnalités | **Toutes** : MinIO, OCR, PDF/A, PostgreSQL, sauvegardes (c'est votre pile Docker) |
| HTTPS | Oui, certificat valide fourni par Cloudflare (pas d'avertissement) |
| Disponibilité | Tant que votre PC est allumé, connecté et que Docker Desktop tourne |
| Adresse | Change à chaque redémarrage du tunnel |

C'est la solution idéale pour une **démonstration**, une soutenance ou pour faire tester l'application par d'autres personnes. Pour un site disponible 24 h/24, voir la dernière section.

---

## 1. Prérequis

SIGED fonctionne sur https://localhost (étape B de [deploiement_oracle.md](deploiement_oracle.md)), et vous connaissez le mot de passe du compte `admin`.

## 2. Mettre en ligne

```powershell
cd D:\Django\siged
git pull
powershell -ExecutionPolicy Bypass -File deploy\windows\en-ligne.ps1
```

Le script :

1. démarre SIGED et le tunnel (`docker compose --profile public up -d`) ;
2. attend que Cloudflare attribue l'adresse publique ;
3. l'affiche, la **copie dans le presse-papiers** et l'ouvre dans le navigateur.

Envoyez cette adresse à qui vous voulez : elle fonctionne depuis n'importe quel téléphone ou ordinateur.

**Sans le script** :

```powershell
docker compose --profile public up -d
docker compose --profile public logs tunnel
```

Cherchez dans le journal la ligne contenant `https://….trycloudflare.com`.

## 3. Retirer le site d'Internet

```powershell
powershell -ExecutionPolicy Bypass -File deploy\windows\hors-ligne.ps1
```

L'application reste disponible pour vous sur https://localhost. Un simple `docker compose up -d` (sans `--profile public`) ne démarre **jamais** le tunnel : rien n'est publié par accident.

## 4. Bonnes pratiques pendant que le site est public

* **Mot de passe administrateur** robuste (celui que vous avez réinitialisé). Créez des comptes `lecteur` ou `contributeur` pour les personnes qui testent, plutôt que de partager `admin`.
* **Données** : n'y mettez que des documents de démonstration (`python -m scripts.demo_data --url https://VOTRE-ADRESSE.trycloudflare.com --password "…"` depuis `backend`).
* **Mise en veille** : désactivez-la pendant une démonstration (*Paramètres Windows → Système → Alimentation → Écran et veille → Jamais*), sinon le site se coupe.
* **Taille des fichiers** : la documentation de Cloudflare fixe à **100 Mo** la taille maximale d'un envoi pour les offres Free et Pro ([erreur 413](https://developers.cloudflare.com/support/troubleshooting/http-status-codes/4xx-client-error/error-413)). Elle ne précise pas de limite propre aux Quick Tunnels : considérez 100 Mo comme le plafond probable et testez un gros fichier avant la démonstration. Au-delà, l'envoi échoue avec une erreur 413 (la limite propre de l'application est `SIGED_MAX_UPLOAD_MB`, 200 Mo par défaut).
* Le journal d'audit (*Conformité*) enregistre toutes les connexions et consultations, avec l'adresse IP des visiteurs.

## 5. Dépannage

| Symptôme | Solution |
|---|---|
| `Échec de docker compose` | Lancez Docker Desktop (baleine verte), puis relancez le script |
| `Adresse introuvable` | `docker compose --profile public logs tunnel` : vérifiez la connexion Internet ; relancez le script |
| L'adresse ne répond plus | Le PC s'est mis en veille ou a redémarré : relancez le script (une **nouvelle** adresse est attribuée) |
| Erreur 502 sur l'adresse publique | L'API démarre encore : attendez 30 s ; sinon `docker compose logs api` |
| Erreur 429 | Plus de 200 requêtes simultanées : limite des tunnels gratuits, réessayez |

## 6. Comment ça marche (pour le rapport)

```
Visiteur ──HTTPS──▶ Cloudflare ◀══ tunnel chiffré sortant ══ conteneur cloudflared ──▶ api:8000
                     (certificat)        (aucun port ouvert sur votre box)          (votre PC)
```

Le conteneur `cloudflared` ouvre une connexion **sortante** vers Cloudflare : aucun port n'est ouvert sur votre box ni sur le pare-feu de Windows, et votre adresse IP n'est pas exposée. Cloudflare termine le HTTPS avec un certificat valide et relaie les requêtes vers l'API dans le réseau Docker. Les fichiers restent chiffrés en AES-256 dans MinIO, sur votre PC.

## 7. Et pour un site disponible 24 h/24 ?

Il faut un serveur allumé en permanence :

* **Oracle Cloud Always Free** : gratuit et complet, mais demande une carte bancaire ([deploiement_oracle.md](deploiement_oracle.md), étape C) ;
* **un petit VPS payant** (environ 4 à 6 € par mois, par exemple Hetzner, Contabo ou OVH) : la même procédure que pour Oracle s'applique telle quelle (`deploy/oracle/installer.sh` fonctionne sur tout serveur Ubuntu).

Les hébergeurs gratuits sans carte (Render, Koyeb…) offrent 512 Mo de mémoire et aucun disque persistant : ils ne peuvent faire tourner ni MinIO ni l'OCR de SIGED.
