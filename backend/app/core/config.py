"""Configuration centralisée (variables d'environnement, préfixe SIGED_)."""
import os
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SECRET = "change-me-in-production-please-32chars-min"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SIGED_", env_file=".env", extra="ignore")

    app_name: str = "SIGED - Système Intégré de Gestion Électronique des Documents"
    environment: str = "dev"  # dev | test | prod
    # Plateforme serverless (Vercel) : détectée automatiquement par la variable VERCEL
    serverless: bool = Field(default_factory=lambda: bool(os.getenv("VERCEL")))

    # --- Base de données (métadonnées, index, audit) ---
    # Accepte aussi DATABASE_URL / POSTGRES_URL injectées par Neon ou Supabase.
    database_url: str = Field("sqlite:///./siged.db",
                              validation_alias=AliasChoices("SIGED_DATABASE_URL", "DATABASE_URL", "POSTGRES_URL"))

    # --- Sécurité ---
    secret_key: str = DEFAULT_SECRET
    access_token_minutes: int = 30
    password_min_length: int = 10
    max_failed_logins: int = 5
    lockout_minutes: int = 15

    # --- Stockage des fichiers physiques ---
    storage_backend: str = "local"  # local | s3
    storage_local_path: Path = Path("./data/storage")
    # Clé AES-256 encodée en base64 (32 octets). Vide = dérivée de secret_key (dev uniquement).
    storage_encryption_key: str = ""
    s3_endpoint_url: str = "http://minio:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "siged-documents"
    s3_region: str = "us-east-1"
    s3_addressing_style: str = "path"  # path (MinIO, Supabase) | virtual (AWS)

    # --- Acquisition ---
    max_upload_mb: int = 200
    inbox_path: Path = Path("./data/inbox")  # dossier partagé surveillé (hot folder)
    ocr_languages: str = "fra+eng"
    enable_conversion: bool = True  # PDF/A + OCR
    process_in_background: bool = True

    # --- Conservation (DUA) ---
    retention_auto_execute: bool = False  # False = bordereau à confirmer par l'archiviste

    # --- Interopérabilité ---
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "siged@localhost"
    imap_host: str = ""
    imap_user: str = ""
    imap_password: str = ""
    imap_folder: str = "INBOX"

    # --- Tâches planifiées déclenchées par HTTP (Vercel Cron) ---
    cron_secret: str = Field("", validation_alias=AliasChoices("SIGED_CRON_SECRET", "CRON_SECRET"))

    # --- Performance ---
    slow_request_ms: int = 2000

    # --- Compte administrateur initial ---
    bootstrap_admin_username: str = "admin"
    bootstrap_admin_password: str = "Admin@SIGED2026"
    bootstrap_admin_email: str = "admin@siged.ga"


    @model_validator(mode="after")
    def _adapt(self):
        url = self.database_url
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                self.database_url = "postgresql+psycopg://" + url[len(prefix):]
        if self.serverless:
            # Pas de tâche de fond après la réponse ni de disque persistant en serverless
            self.process_in_background = False
            self.max_upload_mb = min(self.max_upload_mb, 4)  # corps de requête limité à 4,5 Mo
            if self.storage_backend == "local":
                self.storage_local_path = Path("/tmp/siged/storage")
            self.inbox_path = Path("/tmp/siged/inbox")
        return self

    def production_problems(self) -> list[str]:
        """Contrôles bloquants avant de servir en production."""
        problems = []
        if self.environment == "prod":
            if self.secret_key == DEFAULT_SECRET or len(self.secret_key) < 32:
                problems.append("SIGED_SECRET_KEY doit être défini (32 caractères minimum)")
            if not self.storage_encryption_key:
                problems.append("SIGED_STORAGE_ENCRYPTION_KEY doit être défini")
            if self.database_url.startswith("sqlite") and self.serverless:
                problems.append("SQLite n'est pas persistant en serverless : configurez DATABASE_URL (PostgreSQL)")
            if self.storage_backend == "local" and self.serverless:
                problems.append("Le disque n'est pas persistant en serverless : SIGED_STORAGE_BACKEND=s3 requis")
        return problems


@lru_cache
def get_settings() -> Settings:
    return Settings()
