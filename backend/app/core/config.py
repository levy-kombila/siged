"""Configuration centralisée (variables d'environnement, préfixe SIGED_)."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SIGED_", env_file=".env", extra="ignore")

    app_name: str = "SIGED - Système Intégré de Gestion Électronique des Documents"
    environment: str = "dev"  # dev | test | prod

    # --- Base de données (métadonnées, index, audit) ---
    database_url: str = "sqlite:///./siged.db"

    # --- Sécurité ---
    secret_key: str = "change-me-in-production-please-32chars-min"
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

    # --- Performance ---
    slow_request_ms: int = 2000

    # --- Compte administrateur initial ---
    bootstrap_admin_username: str = "admin"
    bootstrap_admin_password: str = "Admin@SIGED2026"
    bootstrap_admin_email: str = "admin@siged.ga"


@lru_cache
def get_settings() -> Settings:
    return Settings()
