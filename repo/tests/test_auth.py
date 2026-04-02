"""
Prompt 2 – Authentication & Account Security tests.

All 17 tests as specified.
"""
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unique(prefix="user"):
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _register(client, username=None, email=None, password="ValidPass123!"):
    username = username or _unique()
    email = email or f"{username}@example.com"
    resp = client.post(
        "/auth/register",
        json={"username": username, "email": email, "password": password},
    )
    return resp, username, email


def _login(client, username, password="ValidPass123!"):
    return client.post(
        "/auth/login",
        json={"username": username, "password": password},
    )


def _auth_header(token):
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_register_success(client):
    """Valid payload → 201 with user_id in body."""
    resp, username, email = _register(client)
    assert resp.status_code == 201, resp.get_data(as_text=True)
    data = resp.get_json()
    assert "user_id" in data
    assert data["username"] == username


def test_register_duplicate_username(client):
    """Same username → 409."""
    _, username, _ = _register(client)
    # second registration reuses the same username, different email
    resp = client.post(
        "/auth/register",
        json={
            "username": username,
            "email": f"other_{username}@example.com",
            "password": "ValidPass123!",
        },
    )
    assert resp.status_code == 409, resp.get_data(as_text=True)


def test_register_duplicate_email(client):
    """Same email → 409."""
    _, username, email = _register(client)
    resp = client.post(
        "/auth/register",
        json={
            "username": _unique(),
            "email": email,
            "password": "ValidPass123!",
        },
    )
    assert resp.status_code == 409, resp.get_data(as_text=True)


def test_register_short_password(client):
    """11-character password → 422."""
    resp = client.post(
        "/auth/register",
        json={
            "username": _unique(),
            "email": f"{_unique()}@example.com",
            "password": "ShortPass1!",  # exactly 11 chars
        },
    )
    assert resp.status_code == 422, resp.get_data(as_text=True)


def test_register_invalid_username_chars(client):
    """Username with disallowed characters → 422."""
    resp = client.post(
        "/auth/register",
        json={
            "username": "bad name!",
            "email": f"{_unique()}@example.com",
            "password": "ValidPass123!",
        },
    )
    assert resp.status_code == 422, resp.get_data(as_text=True)


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

def test_login_success(client):
    """Correct credentials → 200 with token present."""
    _, username, _ = _register(client)
    resp = _login(client, username)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    data = resp.get_json()
    assert "token" in data
    assert data["token"]


def test_login_wrong_password(client):
    """Wrong password → 401."""
    _, username, _ = _register(client)
    resp = _login(client, username, password="WrongPassword999!")
    assert resp.status_code == 401, resp.get_data(as_text=True)


def test_login_lockout_after_five_failures(client):
    """5 bad attempts → 6th attempt returns 423 with locked_until."""
    _, username, _ = _register(client)

    for _ in range(5):
        resp = _login(client, username, password="WrongPass123!")
        # First five may be 401 (or 423 on the 5th if count hits threshold there)

    # The 6th attempt should be 423 (locked)
    resp = _login(client, username, password="WrongPass123!")
    assert resp.status_code == 423, resp.get_data(as_text=True)
    data = resp.get_json()
    assert "locked_until" in data


def test_login_while_locked(client):
    """Login during lock window → 423."""
    _, username, _ = _register(client)

    # Trigger lockout
    for _ in range(5):
        _login(client, username, password="WrongPass123!")

    # Now try correct password while locked
    resp = _login(client, username)
    assert resp.status_code == 423, resp.get_data(as_text=True)


def test_login_lockout_resets_after_window(client, app):
    """4 bad attempts + simulated time past 15-min window → not locked on next attempt."""
    _, username, _ = _register(client)

    # 4 failures within "now"
    for _ in range(4):
        _login(client, username, password="WrongPass123!")

    # Simulate time advancing past the 15-minute rolling window by patching
    # the datetime.now() call inside auth_service so the window query sees
    # the old attempts as outside the window.
    future_now = datetime.now(timezone.utc) + timedelta(minutes=16)

    with patch(
        "app.services.auth_service.datetime",
        wraps=__import__("datetime").datetime,
    ) as mock_dt:
        mock_dt.now.return_value = future_now

        resp = _login(client, username)
    # With the clock advanced 16 minutes, the 4 old failures are outside the
    # 15-minute window, so the failure count is 0 → login succeeds (200) or
    # at worst records a new failure (401) without triggering lock (423).
    assert resp.status_code != 423, resp.get_data(as_text=True)


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------

def test_logout_success(client):
    """Valid token → 200; same token used again → 401."""
    _, username, _ = _register(client)
    token = _login(client, username).get_json()["token"]

    resp = client.post("/auth/logout", headers=_auth_header(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)

    # Same token is now revoked → 401
    resp2 = client.get("/auth/me", headers=_auth_header(token))
    assert resp2.status_code == 401, resp2.get_data(as_text=True)


# ---------------------------------------------------------------------------
# Refresh
# ---------------------------------------------------------------------------

def test_refresh_token(client):
    """Refresh → new token returned; old token rejected afterwards."""
    _, username, _ = _register(client)
    old_token = _login(client, username).get_json()["token"]

    resp = client.post("/auth/refresh", headers=_auth_header(old_token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    new_token = resp.get_json()["token"]
    assert new_token
    assert new_token != old_token

    # Old token should be rejected
    resp2 = client.get("/auth/me", headers=_auth_header(old_token))
    assert resp2.status_code == 401, resp2.get_data(as_text=True)

    # New token should work
    resp3 = client.get("/auth/me", headers=_auth_header(new_token))
    assert resp3.status_code == 200, resp3.get_data(as_text=True)


# ---------------------------------------------------------------------------
# /me
# ---------------------------------------------------------------------------

def test_me_authenticated(client):
    """Valid token → 200 with username in body."""
    _, username, _ = _register(client)
    token = _login(client, username).get_json()["token"]

    resp = client.get("/auth/me", headers=_auth_header(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    data = resp.get_json()
    assert data["username"] == username


def test_me_unauthenticated(client):
    """No token → 401."""
    resp = client.get("/auth/me")
    assert resp.status_code == 401, resp.get_data(as_text=True)


# ---------------------------------------------------------------------------
# Admin unlock
# ---------------------------------------------------------------------------

def test_admin_unlock(client, app):
    """Admin unlocks a locked user → user can log in again."""
    from app.models.auth import User, Role, UserRole
    from app.extensions import db

    # Create and lock a victim user
    _, victim_username, _ = _register(client, username=_unique("victim"))
    for _ in range(5):
        _login(client, victim_username, password="WrongPass123!")
    # Verify locked
    lock_resp = _login(client, victim_username, password="WrongPass123!")
    assert lock_resp.status_code == 423

    # Create admin user
    admin_username = _unique("admin")
    _register(client, username=admin_username, email=f"{admin_username}@example.com")

    with app.app_context():
        admin_user = User.query.filter_by(username=admin_username).first()
        role = Role.query.filter_by(name="admin").first()
        if role is None:
            role = Role(name="admin")
            db.session.add(role)
            db.session.flush()
        existing = UserRole.query.filter_by(user_id=admin_user.id, role_id=role.id).first()
        if not existing:
            db.session.add(UserRole(user_id=admin_user.id, role_id=role.id))
        db.session.commit()

        victim_user = User.query.filter_by(username=victim_username).first()
        victim_id = victim_user.id

    admin_token = _login(client, admin_username).get_json()["token"]

    resp = client.post(f"/auth/unlock/{victim_id}", headers=_auth_header(admin_token))
    assert resp.status_code == 200, resp.get_data(as_text=True)

    # Victim can now log in with correct password
    resp2 = _login(client, victim_username)
    assert resp2.status_code == 200, resp2.get_data(as_text=True)


def test_non_admin_cannot_unlock(client, app):
    """Regular user trying to unlock → 403."""
    from app.models.auth import User

    # Create a target user (doesn't need to be locked)
    _, target_username, _ = _register(client, username=_unique("target"))
    _, regular_username, _ = _register(client, username=_unique("regular"))

    with app.app_context():
        target_user = User.query.filter_by(username=target_username).first()
        target_id = target_user.id

    regular_token = _login(client, regular_username).get_json()["token"]
    resp = client.post(f"/auth/unlock/{target_id}", headers=_auth_header(regular_token))
    assert resp.status_code == 403, resp.get_data(as_text=True)


# ---------------------------------------------------------------------------
# Expired session
# ---------------------------------------------------------------------------

def test_expired_session_rejected(client, app):
    """Directly expire a session → subsequent request returns 401."""
    from app.models.auth import Session
    from app.extensions import db

    _, username, _ = _register(client, username=_unique("expiry"))
    token = _login(client, username).get_json()["token"]

    # Verify it works before expiry
    resp = client.get("/auth/me", headers=_auth_header(token))
    assert resp.status_code == 200

    # Directly set expires_at to the past
    with app.app_context():
        session = Session.query.filter_by(token=token).first()
        session.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db.session.commit()

    resp2 = client.get("/auth/me", headers=_auth_header(token))
    assert resp2.status_code == 401, resp2.get_data(as_text=True)
