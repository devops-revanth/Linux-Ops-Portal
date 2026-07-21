"""
Symmetric encryption utility for sensitive configuration values.

Uses Fernet (AES-128-CBC + HMAC-SHA256) from the cryptography package.
The key is deterministically derived from Flask's SECRET_KEY so that
encrypted values survive application restarts without extra key management.

Usage:
    from app.encryption import encrypt_value, decrypt_value

    enc = encrypt_value("secret-bind-password")
    plain = decrypt_value(enc)  # "secret-bind-password"

Returns None on any decryption failure so callers can treat missing or
corrupted values gracefully.
"""
from __future__ import annotations

import base64
import hashlib
import logging

logger = logging.getLogger(__name__)

_fernet = None   # lazy singleton


def _get_fernet():
    """Return (and cache) a Fernet instance keyed from Flask's SECRET_KEY."""
    global _fernet
    if _fernet is not None:
        return _fernet

    try:
        from cryptography.fernet import Fernet
        from flask import current_app

        raw_key = current_app.config["SECRET_KEY"]
        if isinstance(raw_key, str):
            raw_key = raw_key.encode()

        # Derive a 32-byte key via SHA-256 and base64-url-encode it
        # to satisfy Fernet's requirement for a 32-byte URL-safe base64 key.
        key_bytes = hashlib.sha256(raw_key).digest()
        fernet_key = base64.urlsafe_b64encode(key_bytes)
        _fernet = Fernet(fernet_key)
        return _fernet
    except Exception as exc:
        logger.error("Failed to initialise Fernet: %s", exc)
        raise


def encrypt_value(plaintext: str) -> str:
    """Encrypt a plain-text string and return a URL-safe base64 token."""
    if not plaintext:
        return ""
    try:
        f = _get_fernet()
        return f.encrypt(plaintext.encode()).decode()
    except Exception as exc:
        logger.error("encrypt_value failed: %s", exc)
        raise


def decrypt_value(ciphertext: str) -> str | None:
    """Decrypt a Fernet token.  Returns None on any failure."""
    if not ciphertext:
        return None
    try:
        f = _get_fernet()
        return f.decrypt(ciphertext.encode()).decode()
    except Exception as exc:
        logger.warning("decrypt_value failed (value may be stale or key changed): %s", exc)
        return None


def reset_fernet_cache() -> None:
    """Clear the cached Fernet instance (call after SECRET_KEY changes in tests)."""
    global _fernet
    _fernet = None
