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


def test_reserve_abandon_challenge(client, app, user_token):
    """4 reserve events in 60 min for same user without checkout → challenge + reserve_abandon."""
    me_resp = client.get("/auth/me", headers=_auth_headers(user_token))
    user_id = me_resp.get_json()["user_id"]

    _seed_risk_events(app, 4, "reserve", user_id=user_id, minutes_ago=30)

    resp = client.post(
        "/risk/evaluate",
        json={"event_type": "reserve", "ip": "10.1.2.3"},
        headers=_auth_headers(user_token),
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["decision"] == "challenge", f"Expected challenge, got {data['decision']}"
    assert "reserve_abandon" in data["reasons"]


def test_coupon_cycling_throttle(client, app):
    """3 coupon_redeem + 3 coupon_refund events in 24h for same user → throttle + coupon_cycling."""
    from app.services.auth_service import register_user, login_user

    # Use a dedicated user so stale events from other tests don't contaminate this check
    with app.app_context():
        try:
            register_user("coupon_cycle_tester", "coupon_cycle@test.com", "CouponPass123!")
        except ValueError:
            pass
        session = login_user("coupon_cycle_tester", "CouponPass123!", ip="127.0.0.1")
        token = session.token
        from app.models.auth import User
        u = User.query.filter_by(username="coupon_cycle_tester").first()
        user_id = u.id

    _seed_risk_events(app, 3, "coupon_redeem", user_id=user_id, minutes_ago=60)
    _seed_risk_events(app, 3, "coupon_refund", user_id=user_id, minutes_ago=60)

    # user_id in body is ignored for non-admins; the service uses g.current_user.id
    resp = client.post(
        "/risk/evaluate",
        json={"event_type": "coupon_redeem", "ip": "10.1.2.4"},
        headers=_auth_headers(token),
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

    # user_id in body is ignored for non-admins
    resp = client.post(
        "/risk/evaluate",
        json={"event_type": "profile_edit", "ip": "10.1.2.5"},
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


def test_blacklisted_user_blocked(client, app, admin_token):
    """Blacklisted user gets 403 on authenticated endpoint."""
    from app.services.auth_service import register_user, login_user

    # Use a dedicated user so the blacklist entry doesn't contaminate other tests
    with app.app_context():
        try:
            register_user("blacklist_victim", "blacklist_victim@test.com", "VictimPass123!")
        except ValueError:
            pass
        session = login_user("blacklist_victim", "VictimPass123!", ip="127.0.0.1")
        victim_token = session.token
        from app.models.auth import User
        victim = User.query.filter_by(username="blacklist_victim").first()
        victim_id = victim.id

    # Create blacklist entry for the victim
    bl_resp = client.post(
        "/risk/blacklist",
        json={
            "target_type": "user",
            "target_id": str(victim_id),
            "reason": "Policy violation",
        },
        headers=_auth_headers(admin_token),
    )
    assert bl_resp.status_code == 201

    # Now the victim should be blocked
    blocked_resp = client.get("/auth/me", headers=_auth_headers(victim_token))
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


def test_appeal_flow(client, app, admin_token):
    """Affected user submits appeal for their own blacklist entry → pending; admin approves → approved."""
    from app.services.auth_service import register_user, login_user

    # Use a dedicated user so the blacklist entry doesn't contaminate other tests
    with app.app_context():
        try:
            register_user("appeal_flow_user", "appeal_flow_user@test.com", "AppealPass123!")
        except ValueError:
            pass
        session = login_user("appeal_flow_user", "AppealPass123!", ip="127.0.0.1")
        appeal_token = session.token
        from app.models.auth import User
        user = User.query.filter_by(username="appeal_flow_user").first()
        user_id = user.id

    # Admin creates a user-type blacklist entry targeting the dedicated user
    bl_resp = client.post(
        "/risk/blacklist",
        json={
            "target_type": "user",
            "target_id": str(user_id),
            "reason": "Flagged for review",
        },
        headers=_auth_headers(admin_token),
    )
    assert bl_resp.status_code == 201
    entry_id = bl_resp.get_json()["id"]

    # Affected user submits appeal for their own entry
    appeal_resp = client.post(
        f"/risk/blacklist/{entry_id}/appeal",
        headers=_auth_headers(appeal_token),
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


# ---------------------------------------------------------------------------
# P1.1: challenge decision
# ---------------------------------------------------------------------------

def test_challenge_decision_returned(client, app):
    """reserve_abandon signal (CHALLENGE severity) → decision == 'challenge'."""
    from app.services.auth_service import register_user, login_user

    # Use a dedicated clean user so HIGH-severity events from other tests don't
    # interfere and elevate the decision to 'deny'.
    with app.app_context():
        try:
            register_user("challenge_test_user", "challenge_test@test.com", "ChallengePass123!")
        except ValueError:
            pass
        session = login_user("challenge_test_user", "ChallengePass123!", ip="127.0.0.1")
        token = session.token
        from app.models.auth import User
        u = User.query.filter_by(username="challenge_test_user").first()
        user_id = u.id

    # Seed enough reserve events to cross the threshold (4) with no checkouts
    _seed_risk_events(app, 4, "reserve", user_id=user_id, minutes_ago=10)

    resp = client.post(
        "/risk/evaluate",
        json={"event_type": "reserve", "ip": "10.5.5.5"},
        headers=_auth_headers(token),
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["decision"] == "challenge"
    assert "reserve_abandon" in data["reasons"]


def test_all_four_decisions_reachable(client, app):
    """Smoke-test that all four decision values are syntactically valid."""
    from app.services.auth_service import register_user, login_user

    valid_decisions = {"allow", "challenge", "throttle", "deny"}

    # Use a dedicated clean user so stale HIGH-severity events don't prevent 'allow'
    with app.app_context():
        try:
            register_user("clean_allow_user", "clean_allow@test.com", "CleanAllowPass123!")
        except ValueError:
            pass
        session = login_user("clean_allow_user", "CleanAllowPass123!", ip="127.0.0.1")
        token = session.token

    # allow – clean event, no prior signals
    r = client.post(
        "/risk/evaluate",
        json={"event_type": "clean_event_unique_1", "ip": "192.168.100.1"},
        headers=_auth_headers(token),
    )
    assert r.get_json()["decision"] in valid_decisions

    # The other decisions are validated individually in dedicated tests above.
    # This test just asserts the allow path returns a known value.
    assert r.get_json()["decision"] == "allow"


# ---------------------------------------------------------------------------
# P1.3: appeal OLA
# ---------------------------------------------------------------------------

def test_appeal_ola_cross_user_forbidden(client, app, admin_token, user_token):
    """User A cannot appeal a user-type blacklist entry that targets user B."""
    from app.services.auth_service import register_user, login_user

    # Create a second user (user B)
    with app.app_context():
        try:
            register_user("appeal_victim", "appeal_victim@test.com", "VictimPass123!")
        except ValueError:
            pass
        session_b = login_user("appeal_victim", "VictimPass123!", ip="127.0.0.1")
        token_b = session_b.token
        from app.models.auth import User
        user_b = User.query.filter_by(username="appeal_victim").first()
        user_b_id = user_b.id

    # Admin blacklists user B
    bl_resp = client.post(
        "/risk/blacklist",
        json={"target_type": "user", "target_id": str(user_b_id), "reason": "test"},
        headers=_auth_headers(admin_token),
    )
    assert bl_resp.status_code == 201
    entry_id = bl_resp.get_json()["id"]

    # User A (user_token fixture) tries to appeal user B's blacklist entry → 403
    resp = client.post(
        f"/risk/blacklist/{entry_id}/appeal",
        headers=_auth_headers(user_token),
    )
    assert resp.status_code == 403

    # User B (the affected user) can appeal their own entry → 200
    resp_b = client.post(
        f"/risk/blacklist/{entry_id}/appeal",
        headers=_auth_headers(token_b),
    )
    assert resp_b.status_code == 200
    assert resp_b.get_json()["appeal_status"] == "pending"


def test_appeal_device_blacklist_requires_admin(client, app, admin_token, user_token):
    """Regular user cannot appeal a device-type blacklist entry (admin/reviewer only)."""
    bl_resp = client.post(
        "/risk/blacklist",
        json={"target_type": "device", "target_id": "device-ola-test", "reason": "test"},
        headers=_auth_headers(admin_token),
    )
    assert bl_resp.status_code == 201
    entry_id = bl_resp.get_json()["id"]

    # Regular user → 403
    resp = client.post(
        f"/risk/blacklist/{entry_id}/appeal",
        headers=_auth_headers(user_token),
    )
    assert resp.status_code == 403

    # Admin → 200
    resp_admin = client.post(
        f"/risk/blacklist/{entry_id}/appeal",
        headers=_auth_headers(admin_token),
    )
    assert resp_admin.status_code == 200


# ---------------------------------------------------------------------------
# P1.5: user_id injection prevention
# ---------------------------------------------------------------------------

def test_risk_evaluate_user_id_forced_to_current_user(client, app):
    """Non-admin cannot inject an arbitrary user_id; the service uses the caller's id."""
    from app.services.auth_service import register_user, login_user

    # Use a dedicated user to avoid blacklist / high-severity contamination
    with app.app_context():
        try:
            register_user("inject_test_user", "inject_test@test.com", "InjectPass123!")
        except ValueError:
            pass
        session = login_user("inject_test_user", "InjectPass123!", ip="127.0.0.1")
        token = session.token
        from app.models.auth import User
        u = User.query.filter_by(username="inject_test_user").first()
        my_id = u.id

    fake_id = my_id + 9999  # an ID that doesn't exist

    resp = client.post(
        "/risk/evaluate",
        json={"event_type": "test_inject", "ip": "10.9.9.9", "user_id": fake_id},
        headers=_auth_headers(token),
    )
    assert resp.status_code == 200
    # The persisted event should record the caller's real user_id, not fake_id
    with app.app_context():
        from app.models.risk import RiskEvent
        event = (
            RiskEvent.query
            .filter_by(event_type="test_inject")
            .order_by(RiskEvent.id.desc())
            .first()
        )
        assert event is not None
        assert event.user_id == my_id, (
            f"Expected user_id={my_id}, got {event.user_id} — user_id injection not prevented"
        )


def test_risk_evaluate_admin_can_specify_arbitrary_user_id(client, app, admin_token):
    """Admin may supply an explicit user_id (e.g. to evaluate on behalf of another user)."""
    target_id = 42  # hypothetical user id

    resp = client.post(
        "/risk/evaluate",
        json={"event_type": "admin_check", "ip": "10.9.9.8", "user_id": target_id},
        headers=_auth_headers(admin_token),
    )
    assert resp.status_code == 200
    with app.app_context():
        from app.models.risk import RiskEvent
        event = (
            RiskEvent.query
            .filter_by(event_type="admin_check")
            .order_by(RiskEvent.id.desc())
            .first()
        )
        assert event is not None
        assert event.user_id == target_id
