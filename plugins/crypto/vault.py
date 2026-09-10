import re
import os
import base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from core.registry import register_cmd
from core.database import Database
from core.errors import CommandError
from helpers.hud import render
from helpers.concurrency import run_in_thread
from config import config

db = Database.get("cryptovault")
PATTERN = rf"^{re.escape(config.PREFIX)}(savenote|getnote|delnote_sec)(?:\s+(.*))?$"

async def setup(client):
    await db.init_schema("""
        CREATE TABLE IF NOT EXISTS secure_notes (
            tag TEXT PRIMARY KEY,
            salt BLOB,
            nonce BLOB,
            ciphertext BLOB
        );
    """)
    register_cmd(client, PATTERN, handle_crypto, "crypto", "AES-256-GCM Encrypted Notes Vault.")

def _derive_key(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=100000)
    return kdf.derive(password.encode())

def _encrypt(password: str, plaintext: str) -> tuple:
    salt = os.urandom(16)
    key = _derive_key(password, salt)
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode(), None)
    return salt, nonce, ciphertext

def _decrypt(password: str, salt: bytes, nonce: bytes, ciphertext: bytes) -> str:
    key = _derive_key(password, salt)
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, None).decode()

async def handle_crypto(event):
    cmd = event.pattern_match.group(1).lower()
    arg = event.pattern_match.group(2)
    
    if cmd == "savenote":
        parts = arg.split(maxsplit=2)
        if len(parts) < 3: raise CommandError("Usage: .savenote <tag> <pass> <content>")
        tag, pwd, content = parts
        
        salt, nonce, ciphertext = await run_in_thread(_encrypt, pwd, content)
        await db.execute("INSERT OR REPLACE INTO secure_notes (tag, salt, nonce, ciphertext) VALUES (?, ?, ?, ?)", 
                         (tag, salt, nonce, ciphertext))
        await event.edit(render("CRYPTO VAULT", [f"Note '{tag}' encrypted and stored."]))
        
    elif cmd == "getnote":
        parts = arg.split(maxsplit=1)
        if len(parts) < 2: raise CommandError("Usage: .getnote <tag> <pass>")
        tag, pwd = parts
        
        row = await db.fetchone("SELECT salt, nonce, ciphertext FROM secure_notes WHERE tag = ?", (tag,))
        if not row: raise CommandError("Note not found.")
        
        try:
            plaintext = await run_in_thread(_decrypt, pwd, row[0], row[1], row[2])
            await event.edit(render("CRYPTO VAULT: DECRYPTED", [f"Tag: {tag}", "---", plaintext]))
        except Exception:
            raise CommandError("Decryption failed. Authentication tag mismatch (wrong passphrase).")

    elif cmd == "delnote_sec":
        await db.execute("DELETE FROM secure_notes WHERE tag = ?", (arg.strip(),))
        await event.edit(render("CRYPTO VAULT", [f"Wiped '{arg}'."]))
