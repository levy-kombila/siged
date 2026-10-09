"""Génère tous les secrets aléatoires de SIGED et affiche des blocs prêts à copier.

    python -m scripts.generer_secrets            (depuis le dossier backend)
    python backend/scripts/generer_secrets.py    (depuis la racine du dépôt)

Le script n'écrit AUCUN fichier : il affiche les valeurs, vous les copiez
vous-même dans .env (Docker) ou dans les variables d'environnement Vercel.
Chaque exécution produit de nouvelles valeurs : ne le relancez pas pour un
système déjà en service (la clé AES déchiffre les fichiers existants).
"""
import base64
import os
import secrets
import string


def mot_de_passe_admin(longueur: int = 16) -> str:
    """Respecte la politique SIGED : ≥ 10 caractères, minuscules, majuscules, chiffres, symbole."""
    alphabet = string.ascii_letters + string.digits
    while True:
        base = "".join(secrets.choice(alphabet) for _ in range(longueur - 2))
        pwd = base + secrets.choice("@#%+=") + secrets.choice(string.digits)
        if any(c.islower() for c in pwd) and any(c.isupper() for c in pwd):
            return pwd


def main() -> None:
    secret_key = secrets.token_urlsafe(48)
    aes_key = base64.b64encode(os.urandom(32)).decode()
    pg_password = secrets.token_hex(16)        # hexadécimal : sans caractère à encoder dans une URL
    minio_password = secrets.token_hex(20)
    cron_secret = secrets.token_urlsafe(24)
    admin_password = mot_de_passe_admin()

    print("=" * 78)
    print(" SECRETS SIGED — à conserver dans un gestionnaire de mots de passe")
    print(" (Bitwarden, KeePassXC...). Ne jamais les committer sur GitHub.")
    print("=" * 78)
    print(f"""
# ---------- Bloc 1 : déploiement Docker (à recopier dans .env) ----------
SIGED_ENVIRONMENT=prod
SIGED_SECRET_KEY={secret_key}
SIGED_STORAGE_ENCRYPTION_KEY={aes_key}

POSTGRES_DB=siged
POSTGRES_USER=siged
POSTGRES_PASSWORD={pg_password}
SIGED_DATABASE_URL=postgresql+psycopg://siged:{pg_password}@postgres:5432/siged

SIGED_STORAGE_BACKEND=s3
SIGED_S3_ENDPOINT_URL=http://minio:9000
SIGED_S3_ACCESS_KEY=siged
SIGED_S3_SECRET_KEY={minio_password}
SIGED_S3_BUCKET=siged-documents
MINIO_ROOT_USER=siged
MINIO_ROOT_PASSWORD={minio_password}

SIGED_BOOTSTRAP_ADMIN_PASSWORD={admin_password}

# ---------- Bloc 2 : Vercel (Settings > Environment Variables) ----------
SIGED_ENVIRONMENT=prod
SIGED_SECRET_KEY={secret_key}
SIGED_STORAGE_ENCRYPTION_KEY={aes_key}
SIGED_BOOTSTRAP_ADMIN_PASSWORD={admin_password}
CRON_SECRET={cron_secret}
SIGED_STORAGE_BACKEND=s3
SIGED_S3_BUCKET=siged-documents
# + SIGED_S3_ENDPOINT_URL, SIGED_S3_REGION, SIGED_S3_ACCESS_KEY, SIGED_S3_SECRET_KEY : fournis par Supabase
# + DATABASE_URL : ajoutée automatiquement par Neon
""")
    print("RAPPEL : sans SIGED_STORAGE_ENCRYPTION_KEY, les fichiers stockés sont irrécupérables.")
    print("Gardez-en une copie hors du serveur (gestionnaire de mots de passe + copie papier sous scellé).")


if __name__ == "__main__":
    main()
