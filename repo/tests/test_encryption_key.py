"""
Tests for FIELD_ENCRYPTION_KEY startup validation.

The app must fail fast with a clear RuntimeError when:
  - The key is valid base64 but decodes to something other than 32 bytes
  - The key is not valid base64

And must start normally when the key decodes to exactly 32 bytes.
"""
import base64
import os

import pytest


def _make_app_with_key(key_env_value, config=None):
    """Attempt to create the app with the given raw env string. Returns the app."""
    original = os.environ.get("FIELD_ENCRYPTION_KEY")
    try:
        os.environ["FIELD_ENCRYPTION_KEY"] = key_env_value
        from app import create_app
        return create_app(config or {"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    finally:
        if original is None:
            os.environ.pop("FIELD_ENCRYPTION_KEY", None)
        else:
            os.environ["FIELD_ENCRYPTION_KEY"] = original


# ---------------------------------------------------------------------------
# Invalid-length key tests
# ---------------------------------------------------------------------------

def test_startup_rejects_16_byte_key():
    """A 16-byte (AES-128) key must be rejected at startup."""
    short_key = base64.b64encode(os.urandom(16)).decode()
    with pytest.raises(RuntimeError, match="32 bytes"):
        _make_app_with_key(short_key)


def test_startup_rejects_24_byte_key():
    """A 24-byte (AES-192) key must be rejected at startup."""
    mid_key = base64.b64encode(os.urandom(24)).decode()
    with pytest.raises(RuntimeError, match="32 bytes"):
        _make_app_with_key(mid_key)


def test_startup_rejects_64_byte_key():
    """A 64-byte key (double the required length) must be rejected."""
    long_key = base64.b64encode(os.urandom(64)).decode()
    with pytest.raises(RuntimeError, match="32 bytes"):
        _make_app_with_key(long_key)


# ---------------------------------------------------------------------------
# Invalid base64 test
# ---------------------------------------------------------------------------

def test_startup_rejects_non_base64_key():
    """A string that is not valid base64 must be rejected at startup."""
    with pytest.raises(RuntimeError, match="not valid base64"):
        _make_app_with_key("this is not base64!!!")


# ---------------------------------------------------------------------------
# get_encryption_key unit tests
# ---------------------------------------------------------------------------

def test_get_encryption_key_rejects_wrong_length(monkeypatch):
    """encryption_service.get_encryption_key() raises RuntimeError for non-32-byte key."""
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", base64.b64encode(os.urandom(16)).decode())
    from app.services import encryption_service
    import importlib
    importlib.reload(encryption_service)
    with pytest.raises(RuntimeError, match="32 bytes"):
        encryption_service.get_encryption_key()


def test_get_encryption_key_rejects_bad_base64(monkeypatch):
    """encryption_service.get_encryption_key() raises RuntimeError for invalid base64."""
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", "!!! not base64 !!!")
    from app.services import encryption_service
    import importlib
    importlib.reload(encryption_service)
    with pytest.raises(RuntimeError, match="not valid base64"):
        encryption_service.get_encryption_key()


def test_get_encryption_key_accepts_32_byte_key(monkeypatch):
    """encryption_service.get_encryption_key() returns 32-byte key without error."""
    valid_key = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", valid_key)
    from app.services import encryption_service
    import importlib
    importlib.reload(encryption_service)
    key = encryption_service.get_encryption_key()
    assert len(key) == 32


# ---------------------------------------------------------------------------
# Successful startup test
# ---------------------------------------------------------------------------

def test_startup_accepts_valid_32_byte_key():
    """App starts normally when FIELD_ENCRYPTION_KEY is base64(32 random bytes)."""
    import tempfile
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(db_fd)
    try:
        valid_key = base64.b64encode(os.urandom(32)).decode()
        app = _make_app_with_key(
            valid_key,
            config={"TESTING": True, "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}"},
        )
        assert app is not None
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass
