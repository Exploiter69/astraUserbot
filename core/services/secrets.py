"""Encrypted secret storage with explicit master-key configuration."""

from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from core.database import Database

_PREFIX = "v1:"
_ITERATIONS = 200_000


class SecretStoreError(RuntimeError):
    pass


def _derive_key(master_key: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=_ITERATIONS,
    )
    return kdf.derive(master_key.encode("utf-8"))


class SecretStore:
    """Persist secrets encrypted at rest using AES-256-GCM."""

    def __init__(self, db: Database | None = None, master_key: str | None = None) -> None:
        self.db = db or Database.get("vault")
        self.master_key = master_key if master_key is not None else os.getenv("ASTRA_VAULT_KEY", "")
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        if not self.master_key:
            return
        await self.db.init_schema(
            """
            CREATE TABLE IF NOT EXISTS secrets (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        self._started = True

    async def close(self) -> None:
        self._started = False

    async def _ensure_started(self) -> None:
        if not self.master_key:
            raise SecretStoreError("ASTRA_VAULT_KEY is not configured")
        if not self._started:
            await self.start()
        if not self._started:
            raise SecretStoreError("Secret store is unavailable")

    def _encrypt(self, plaintext: str) -> str:
        salt = os.urandom(16)
        nonce = os.urandom(12)
        key = _derive_key(self.master_key, salt)
        ciphertext = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), None)
        payload = salt + nonce + ciphertext
        return _PREFIX + base64.urlsafe_b64encode(payload).decode("ascii")

    def _decrypt(self, encoded: str) -> str:
        if not encoded.startswith(_PREFIX):
            raise SecretStoreError("Secret uses an unsupported storage format")
        try:
            payload = base64.urlsafe_b64decode(encoded[len(_PREFIX):].encode("ascii"))
            salt, nonce, ciphertext = payload[:16], payload[16:28], payload[28:]
            key = _derive_key(self.master_key, salt)
            return AESGCM(key).decrypt(nonce, ciphertext, None).decode("utf-8")
        except Exception as exc:
            raise SecretStoreError("Secret decryption failed") from exc

    async def set(self, key: str, value: str) -> None:
        await self._ensure_started()
        if not key or len(key) > 128:
            raise SecretStoreError("Invalid secret key")
        await self.db.execute(
            "INSERT OR REPLACE INTO secrets (key, value) VALUES (?, ?)",
            (key, self._encrypt(value)),
        )

    async def get(self, key: str) -> str | None:
        await self._ensure_started()
        row = await self.db.fetchone("SELECT value FROM secrets WHERE key = ?", (key,))
        if not row:
            return None
        encoded = row[0]
        if encoded.startswith(_PREFIX):
            return self._decrypt(encoded)

        # Legacy entries were base64-obfuscated rather than encrypted.
        try:
            plaintext = base64.b64decode(encoded.encode("ascii"), validate=True).decode("utf-8")
        except Exception as exc:
            raise SecretStoreError("Legacy secret could not be decoded") from exc
        await self.set(key, plaintext)
        return plaintext

    async def delete(self, key: str) -> None:
        await self._ensure_started()
        await self.db.execute("DELETE FROM secrets WHERE key = ?", (key,))

    async def keys(self) -> list[str]:
        await self._ensure_started()
        rows = await self.db.fetchall("SELECT key FROM secrets ORDER BY key")
        return [row[0] for row in rows]
