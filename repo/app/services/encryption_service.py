"""
Field-level encryption using AES-256-GCM.
"""
import os
import base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def get_encryption_key():
    """Load FIELD_ENCRYPTION_KEY from env, decode from base64, assert 32-byte length.

    Raises RuntimeError on missing key, invalid base64, or wrong decoded length.
    AES-256-GCM requires exactly a 32-byte (256-bit) key.
    """
    key_b64 = os.environ.get("FIELD_ENCRYPTION_KEY")
    if not key_b64:
        raise RuntimeError("FIELD_ENCRYPTION_KEY not set")
    try:
        key = base64.b64decode(key_b64)
    except Exception as exc:
        raise RuntimeError(
            f"FIELD_ENCRYPTION_KEY is not valid base64: {exc}"
        ) from exc
    if len(key) != 32:
        raise RuntimeError(
            f"FIELD_ENCRYPTION_KEY must decode to exactly 32 bytes for AES-256. "
            f"Got {len(key)} bytes."
        )
    return key


def encrypt_field(plaintext: str) -> str:
    """Encrypt with AES-256-GCM. Return base64-encoded nonce+ciphertext."""
    if not plaintext:
        return None
    key = get_encryption_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(nonce + ciphertext).decode()


def decrypt_field(encrypted: str) -> str:
    """Decrypt AES-256-GCM encrypted field."""
    if not encrypted:
        return None
    key = get_encryption_key()
    aesgcm = AESGCM(key)
    data = base64.b64decode(encrypted)
    nonce, ciphertext = data[:12], data[12:]
    return aesgcm.decrypt(nonce, ciphertext, None).decode()


def mask_phone(decrypted_phone=None):
    """Return '***-***-XXXX' mask."""
    return "***-***-XXXX"


def mask_address():
    return "[REDACTED]"


def mask_dob():
    return "[REDACTED]"
