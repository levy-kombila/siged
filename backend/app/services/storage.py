"""Stockage des fichiers physiques, séparé de la base SQL.

Deux backends interchangeables (SIGED_STORAGE_BACKEND) :
  * local : système de fichiers (volume dédié, NAS...)
  * s3    : Object Storage compatible S3 (MinIO, AWS S3, Ceph...)
Dans les deux cas, le contenu est chiffré côté serveur applicatif en AES-256-GCM
AVANT d'être écrit : le stockage ne voit jamais de données en clair.
"""
import os
import shutil
import tempfile
from pathlib import Path
from typing import BinaryIO, Iterator

from app.core.config import get_settings
from app.core.crypto import decrypt_stream, encrypt_stream


class StorageBackend:
    def put(self, key: str, fileobj: BinaryIO) -> None: ...
    def get(self, key: str) -> BinaryIO: ...
    def delete(self, key: str) -> None: ...
    def exists(self, key: str) -> bool: ...
    def ping(self) -> bool: return True


class LocalBackend(StorageBackend):
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if not str(p).startswith(str(self.root.resolve())):
            raise ValueError("Clé de stockage invalide")
        return p

    def put(self, key, fileobj):
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".part")
        with open(tmp, "wb") as out:
            shutil.copyfileobj(fileobj, out)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, p)  # écriture atomique

    def get(self, key):
        return open(self._path(key), "rb")

    def delete(self, key):
        p = self._path(key)
        if p.exists():
            p.unlink()

    def exists(self, key):
        return self._path(key).exists()

    def ping(self):
        return self.root.exists()


class S3Backend(StorageBackend):
    def __init__(self):
        import boto3  # import paresseux
        from botocore.config import Config

        s = get_settings()
        self.bucket = s.s3_bucket
        cfg = Config(
            s3={"addressing_style": s.s3_addressing_style},
            # Les stockages compatibles S3 (Supabase, R2, MinIO anciens) refusent souvent
            # les sommes de contrôle CRC32 ajoutées par défaut depuis boto3 1.36.
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
            retries={"max_attempts": 3, "mode": "standard"},
        )
        self.client = boto3.client(
            "s3", endpoint_url=s.s3_endpoint_url or None, aws_access_key_id=s.s3_access_key,
            aws_secret_access_key=s.s3_secret_key, region_name=s.s3_region, config=cfg)
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except Exception:
            self.client.create_bucket(Bucket=self.bucket)

    def put(self, key, fileobj):
        self.client.upload_fileobj(fileobj, self.bucket, key)

    def get(self, key):
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"]

    def delete(self, key):
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def exists(self, key):
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False

    def ping(self):
        try:
            self.client.head_bucket(Bucket=self.bucket)
            return True
        except Exception:
            return False


class EncryptedStorage:
    """Façade utilisée par l'application : chiffre à l'écriture, déchiffre à la lecture."""

    def __init__(self, backend: StorageBackend):
        self.backend = backend

    def save_file(self, key: str, path: str | Path) -> None:
        with open(path, "rb") as src, tempfile.TemporaryFile() as enc:
            encrypt_stream(src, enc)
            enc.seek(0)
            self.backend.put(key, enc)

    def iter_plain(self, key: str) -> Iterator[bytes]:
        f = self.backend.get(key)
        try:
            yield from decrypt_stream(f)
        finally:
            f.close()

    def read_to_file(self, key: str, dst_path: str | Path) -> None:
        with open(dst_path, "wb") as out:
            for chunk in self.iter_plain(key):
                out.write(chunk)

    def delete(self, key: str) -> None:
        self.backend.delete(key)

    def exists(self, key: str) -> bool:
        return self.backend.exists(key)

    def ping(self) -> bool:
        return self.backend.ping()


_storage: EncryptedStorage | None = None


def get_storage() -> EncryptedStorage:
    global _storage
    if _storage is None:
        s = get_settings()
        backend = S3Backend() if s.storage_backend == "s3" else LocalBackend(s.storage_local_path)
        _storage = EncryptedStorage(backend)
    return _storage


def reset_storage() -> None:
    global _storage
    _storage = None
