"""
Tests for Risk Control & Anomaly Detection (Prompt 3).
"""
import json
from datetime import datetime, timezone, timedelta

import pytest

from app.extensions import db as _db
from app.models.risk import RiskEvent, Blacklist
from app.models.auth import LoginAttempt


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def _seed_risk_events(app, count, event_type, ip=None, user_id=None, minutes_ago=1):
    """Seed `count` RiskEvent rows within the active time window."""
    with app.app_context():
        for _ in range(count):
            event = RiskEvent(
                event_type=event_type,
                ip=ip,
                user_id=user_id,
                decision="allow",
                created_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
            )
            _db.session.add(event)
        _db.session.commit()


def _seed_login_failures(app, count, ip, distinct=True):
    """Seed `count` distinct-user login failure rows from `ip` within 5 min."""
    with app.app_context():
        for i in range(count):
            attempt = LoginAttempt(
                user_id=i + 9000 if distinct else 9000,  # distinct user IDs when distinct=True
                ip=ip,
                success=False,
                attempted_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            )
            _db.session.add(attempt)
        _db.session.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_evaluate_allow_clean(client, user_token):
    """A single clean event with no prior signals → allow."""
    resp = client.post(
        "/risk/evaluate",
        json={"event_type": "page_view", "ip": "10.0.0.1"},
        headers=_auth_headers(user_token),
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["decision"] == "allow"
    assert data["reasons"] == []


def test_rapid_account_creation_deny(client, app, user_token):
    """3 registration events from same IP in 10 min → deny + rapid_account_creation."""
    ip = "203.0.113.10"
    _seed_risk_events(app, 3, "registration", ip=ip, minutes_ago=5)

    resp = client.post(
        "/risk/evaluate",
        json={"event_type": "registration", "ip": ip},
        headers=_auth_headers(user_token),
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["decision"] == "deny"
    assert "rapid_account_creation" in data["reasons"]


def test_credential_stuffing_deny(client, app, user_token):
    """10 distinct user login failures from same IP in 5 min → deny + credential_stuffing."""
    ip = "203.0.113.20"
    _seed_login_failures(app, 10, ip=ip)

    resp = client.post(
        "/risk/evaluate",
        json={"event_type": "login", "ip": ip},
        headers=_auth_headers(user_token),
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["decision"] == "deny"
    assert "credential_stuffing" in data["reasons"]


def test_reserve_abandon_throttle(client, app, user_token):
    """4 reserve events in 60 min for same user without checkout → throttle + reserve_abandon."""
    # Get user ID from token
    me_resp = client.get("/auth/me", headers=_auth_headers(user_token))
    user_id = me_resp.get_json()["user_id"]

    _seed_risk_events(app, 4, "reserve", user_id=user_id, minutes_ago=30)

    resp = client.post(
        "/risk/evaluate",
        json={"event_type": "reserve", "ip": "10.1.2.3", "user_id": user_id},
        headers=_auth_headers(user_token),
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["decision"] == "throttle"
    assert "reserve_abandon" in data["reasons"]


def test_coupon_cycling_throttle(client, app, user_token):
    """3 coupon_redeem + 3 coupon_refund events in 24h for same user → throttle + coupon_cycling."""
    me_resp = client.get("/auth/me", headers=_auth_headers(user_token))
    user_id = me_resp.get_json()["user_id"]

    _seed_risk_events(app, 3, "coupon_redeem", user_id=user_id, minutes_ago=60)
    _seed_risk_events(app, 3, "coupon_refund", user_id=user_id, minutes_ago=60)

    resp = client.post(
        "/risk/evaluate",
        json={"event_type": "coupon_redeem", "ip": "10.1.2.4", "user_id": user_id},
        headers=_auth_headers(user_token),
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["decision"] == "throttle"
    assert "coupon_cycling" in data["reasons"]


def test_high_velocity_profile_edit_deny(client, app, user_token):
    """5 profile_edit events in 10 min for same user → deny + high_velocity_profile_edit."""
    me_resp = client.get("/auth/me", headers=_auth_headers(user_token))
    user_id = me_resp.get_json()["user_id"]

    _seed_risk_events(app, 5, "profile_edit", user_id=user_id, minutes_ago=5)

    resp = client.post(
        "/risk/evaluate",
        json={"event_type": "profile_edit", "ip": "10.1.2.5", "user_id": user_id},
        headers=_auth_headers(user_token),
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["decision"] == "deny"
    assert "high_velocity_profile_edit" in data["reasons"]


def test_risk_event_persisted(client, app, user_token):
    """Any evaluate call → a RiskEvent row is created in the DB."""
    with app.app_context():
        before_count = _db.session.query(RiskEvent).count()

    resp = client.post(
        "/risk/evaluate",
        json={"event_type": "download", "ip": "10.99.99.1"},
        headers=_auth_headers(user_token),
    )
    assert resp.status_code == 200

    with app.app_context():
        after_count = _db.session.query(RiskEvent).count()

    assert after_count == before_count + 1


def test_blacklist_create(client, admin_token):
    """Admin POST /risk/blacklist → 201; entry visible in GET /risk/blacklist."""
    resp = client.post(
        "/risk/blacklist",
        json={
            "target_type": "ip",
            "target_id": "198.51.100.1",
            "reason": "Suspicious scanning activity",
        },
        headers=_auth_headers(admin_token),
    )
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["target_type"] == "ip"
    assert data["target_id"] == "198.51.100.1"
    entry_id = data["id"]

    get_resp = client.get("/risk/blacklist", headers=_auth_headers(admin_token))
    assert get_resp.status_code == 200
    entries = get_resp.get_json()
    ids = [e["id"] for e in entries]
    assert entry_id in ids


def test_blacklist_soft_delete(client, admin_token):
    """DELETE /risk/blacklist/{id} → end_at set; entry no longer in active list."""
    create_resp = client.post(
        "/risk/blacklist",
        json={
            "target_type": "device",
            "target_id": "device-abc-123",
            "reason": "Compromised device",
        },
        headers=_auth_headers(admin_token),
    )
    assert create_resp.status_code == 201
    entry_id = create_resp.get_json()["id"]

    del_resp = client.delete(
        f"/risk/blacklist/{entry_id}",
        headers=_auth_headers(admin_token),
    )
    assert del_resp.status_code == 200

    get_resp = client.get("/risk/blacklist", headers=_auth_headers(admin_token))
    assert get_resp.status_code == 200
    ids = [e["id"] for e in get_resp.get_json()]
    assert entry_id not in ids


def test_blacklisted_user_blocked(client, app, admin_token, user_token):
    """Blacklisted user gets 403 on authenticated endpoint."""
    me_resp = client.get("/auth/me", headers=_auth_headers(user_token))
    assert me_resp.status_code == 200
    user_id = me_resp.get_json()["user_id"]

    # Create blacklist entry for the user
    bl_resp = client.post(
        "/risk/blacklist",
        json={
            "target_type": "user",
            "target_id": str(user_id),
            "reason": "Policy violation",
        },
        headers=_auth_headers(admin_token),
    )
    assert bl_resp.status_code == 201

    # Now the user should be blocked
    blocked_resp = client.get("/auth/me", headers=_auth_headers(user_token))
    assert blocked_resp.status_code == 403


def test_blacklisted_ip_blocked(client, app, admin_token):
    """Request from a blacklisted IP → 403."""
    blocked_ip = "192.0.2.1"

    # Register + login a new user for this test (separate from fixtures)
    client.post(
        "/auth/register",
        json={
            "username": "ipblocktest",
            "email": "ipblocktest@example.com",
            "password": "IpBlockPass123!",
        },
    )
    login_resp = client.post(
        "/auth/login",
        json={"username": "ipblocktest", "password": "IpBlockPass123!"},
    )
    token = login_resp.get_json()["token"]

    # Blacklist the IP
    bl_resp = client.post(
        "/risk/blacklist",
        json={
            "target_type": "ip",
            "target_id": blocked_ip,
            "reason": "Known attack source",
        },
        headers=_auth_headers(admin_token),
    )
    assert bl_resp.status_code == 201

    # Make a request appearing to come from the blacklisted IP
    blocked_resp = client.get(
        "/auth/me",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Forwarded-For": blocked_ip,
        },
    )
    assert blocked_resp.status_code == 403


def test_appeal_flow(client, app, admin_token, user_token):
    """User submits appeal → pending; admin approves → approved."""
    # Admin creates blacklist entry
    bl_resp = client.post(
        "/risk/blacklist",
        json={
            "target_type": "device",
            "target_id": "device-appeal-test",
            "reason": "Flagged for review",
        },
        headers=_auth_headers(admin_token),
    )
    assert bl_resp.status_code == 201
    entry_id = bl_resp.get_json()["id"]

    # User submits appeal
    appeal_resp = client.post(
        f"/risk/blacklist/{entry_id}/appeal",
        headers=_auth_headers(user_token),
    )
    assert appeal_resp.status_code == 200
    assert appeal_resp.get_json()["appeal_status"] == "pending"

    # Admin approves the appeal
    patch_resp = client.patch(
        f"/risk/blacklist/{entry_id}/appeal",
        json={"appeal_status": "approved"},
        headers=_auth_headers(admin_token),
    )
    assert patch_resp.status_code == 200
    assert patch_resp.get_json()["appeal_status"] == "approved"


def test_non_admin_cannot_create_blacklist(client, user_token):
    """Regular user POST /risk/blacklist → 403."""
    resp = client.post(
        "/risk/blacklist",
        json={
            "target_type": "ip",
            "target_id": "10.0.0.99",
            "reason": "Test",
        },
        headers=_auth_headers(user_token),
    )
    assert resp.status_code == 403
