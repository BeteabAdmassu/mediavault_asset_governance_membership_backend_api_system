"""
Field-level encryption using AES-256-GCM.
"""
import os
import base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def get_encryption_key():
    """Load FIELD_ENCRYPTION_KEY from env, decode from base64."""
    key_b64 = os.environ.get("FIELD_ENCRYPTION_KEY")
    if not key_b64:
        raise RuntimeError("FIELD_ENCRYPTION_KEY not set")
    return base64.b64decode(key_b64)


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
