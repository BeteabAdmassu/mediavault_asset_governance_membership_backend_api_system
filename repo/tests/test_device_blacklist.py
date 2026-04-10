"""
Tests for device blacklist enforcement at auth/protected boundaries.

Device identity is supplied via the X-Device-Id request header.
When an active blacklist entry exists for target_type="device" matching
that header value, the request is denied with 403 + code "device_blacklisted".
"""
from datetime import datetime, timezone, timedelta

import pytest

from app.extensions import db as _db
from app.models.risk import Blacklist


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _auth_headers(token, device_id=None):
    headers = {"Authorization": f"Bearer {token}"}
    if device_id:
        headers["X-Device-Id"] = device_id
    return headers


def _block_device(app, device_id, end_at=None):
    """Insert an active Blacklist entry for the given device_id."""
    with app.app_context():
        entry = Blacklist(
            target_type="device",
            target_id=device_id,
            reason="test block",
            start_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            end_at=end_at,
        )
        _db.session.add(entry)
        _db.session.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_blocked_device_denied_on_auth_me(client, app, user_token):
    """An active device blacklist entry blocks /auth/me with 403."""
    device_id = "device-test-001"
    _block_device(app, device_id)

    resp = client.get(
        "/auth/me",
        headers=_auth_headers(user_token, device_id=device_id),
    )
    assert resp.status_code == 403
    data = resp.get_json()
    assert data["error"] == "forbidden"
    assert data["code"] == "device_blacklisted"


def test_blocked_device_denied_on_risk_evaluate(client, app, user_token):
    """An active device blacklist entry blocks /risk/evaluate with 403."""
    device_id = "device-test-002"
    _block_device(app, device_id)

    resp = client.post(
        "/risk/evaluate",
        json={"event_type": "page_view", "ip": "10.0.0.1"},
        headers=_auth_headers(user_token, device_id=device_id),
    )
    assert resp.status_code == 403
    data = resp.get_json()
    assert data["error"] == "forbidden"
    assert data["code"] == "device_blacklisted"


def test_blocked_device_denied_on_write_endpoint(client, app, admin_token):
    """An active device blacklist entry blocks a write endpoint (POST /policies)."""
    device_id = "device-test-003"
    _block_device(app, device_id)

    resp = client.post(
        "/policies",
        json={
            "policy_type": "risk",
            "name": "Test",
            "semver": "1.0.0",
            "effective_from": "2026-01-01T00:00:00",
            "rules_json": '{"rapid_account_creation_threshold": 5}',
        },
        headers=_auth_headers(admin_token, device_id=device_id),
    )
    assert resp.status_code == 403
    data = resp.get_json()
    assert data["error"] == "forbidden"
    assert data["code"] == "device_blacklisted"


def test_clean_device_allowed(client, user_token):
    """A device with no blacklist entry is allowed through normally."""
    resp = client.get(
        "/auth/me",
        headers=_auth_headers(user_token, device_id="clean-device-999"),
    )
    assert resp.status_code == 200


def test_no_device_header_allowed(client, user_token):
    """Requests without X-Device-Id header pass the device check unconditionally."""
    resp = client.get(
        "/auth/me",
        headers=_auth_headers(user_token),  # no device_id kwarg
    )
    assert resp.status_code == 200


def test_expired_device_blacklist_allowed(client, app, user_token):
    """A device blacklist entry whose end_at is in the past is not enforced."""
    device_id = "device-expired-001"
    # Set end_at to 1 hour ago → blacklist has expired
    expired_end = datetime.now(timezone.utc) - timedelta(hours=1)
    _block_device(app, device_id, end_at=expired_end)

    resp = client.get(
        "/auth/me",
        headers=_auth_headers(user_token, device_id=device_id),
    )
    assert resp.status_code == 200


def test_future_start_device_blacklist_allowed(client, app, user_token):
    """A device blacklist entry whose start_at is in the future is not yet active."""
    device_id = "device-future-001"
    with app.app_context():
        entry = Blacklist(
            target_type="device",
            target_id=device_id,
            reason="future block",
            start_at=datetime.now(timezone.utc) + timedelta(hours=1),
            end_at=None,
        )
        _db.session.add(entry)
        _db.session.commit()

    resp = client.get(
        "/auth/me",
        headers=_auth_headers(user_token, device_id=device_id),
    )
    assert resp.status_code == 200


def test_device_blacklist_error_shape(client, app, user_token):
    """403 response for blocked device has the required JSON fields."""
    device_id = "device-shape-check"
    _block_device(app, device_id)

    resp = client.get(
        "/auth/me",
        headers=_auth_headers(user_token, device_id=device_id),
    )
    assert resp.status_code == 403
    data = resp.get_json()
    # Must contain all three machine-readable fields
    assert "error" in data
    assert "message" in data
    assert "code" in data
    assert data["code"] == "device_blacklisted"
