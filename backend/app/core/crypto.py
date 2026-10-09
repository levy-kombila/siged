"""Chiffrement au repos AES-256-GCM, par blocs (streaming), avant écriture dans le stockage.

Format du fichier chiffré :
    MAGIC(6) "SGED1\\n" | nonce_prefix(8) | { len(4, big-endian) | bloc chiffré + tag(16) }*
Chaque bloc utilise le nonce = nonce_prefix || compteur(4) et des données associées
(AAD) = index(8) || drapeau_dernier_bloc(1) : un bloc retiré, permuté ou une
troncature du fichier sont donc détectés au déchiffrement.
"""
import base64
import hashlib
import os
import struct
from typing import BinaryIO, Iterator

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings

MAGIC = b"SGED1\n"
CHUNK = 1024 * 1024  # 1 Mio


class DecryptionError(Exception):
    pass


def get_key() -> bytes:
    s = get_settings()
    if s.storage_encryption_key:
        key = base64.b64decode(s.storage_encryption_key)
        if len(key) != 32:
            raise ValueError("SIGED_STORAGE_ENCRYPTION_KEY doit faire 32 octets (AES-256) encodés en base64")
        return key
    if s.environment == "prod":
        raise ValueError("SIGED_STORAGE_ENCRYPTION_KEY est obligatoire en production")
    return hashlib.sha256(("storage:" + s.secret_key).encode()).digest()


def _aad(index: int, last: bool) -> bytes:
    return struct.pack(">QB", index, 1 if last else 0)


def encrypt_stream(src: BinaryIO, dst: BinaryIO, key: bytes | None = None) -> int:
    """Chiffre src vers dst. Retourne le nombre d'octets écrits."""
    aes = AESGCM(key or get_key())
    prefix = os.urandom(8)
    dst.write(MAGIC + prefix)
    written = len(MAGIC) + 8
    index = 0
    current = src.read(CHUNK)
    while True:
        nxt = src.read(CHUNK)
        last = not nxt
        nonce = prefix + struct.pack(">I", index)
        ct = aes.encrypt(nonce, current, _aad(index, last))
        dst.write(struct.pack(">I", len(ct)) + ct)
        written += 4 + len(ct)
        if last:
            return written
        current, index = nxt, index + 1


def decrypt_stream(src: BinaryIO, key: bytes | None = None) -> Iterator[bytes]:
    """Générateur : déchiffre bloc par bloc (utilisable en StreamingResponse)."""
    aes = AESGCM(key or get_key())
    header = src.read(len(MAGIC) + 8)
    if len(header) != len(MAGIC) + 8 or not header.startswith(MAGIC):
        raise DecryptionError("En-tête de fichier chiffré invalide")
    prefix = header[len(MAGIC):]
    index = 0
    size_raw = src.read(4)
    if not size_raw:
        raise DecryptionError("Fichier chiffré vide")
    while size_raw:
        (size,) = struct.unpack(">I", size_raw)
        ct = src.read(size)
        if len(ct) != size:
            raise DecryptionError("Fichier chiffré tronqué")
        size_raw = src.read(4)
        last = not size_raw
        try:
            yield aes.decrypt(prefix + struct.pack(">I", index), ct, _aad(index, last))
        except Exception as exc:  # InvalidTag
            raise DecryptionError(f"Bloc {index} altéré ou clé invalide") from exc
        index += 1
