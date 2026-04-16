"""
Extended risk tests covering IP blacklist enforcement on evaluate,
risk event listing with filters, and appeal authorization edge cases.

Route contract (from app/api/risk.py):
  POST /risk/evaluate     → 200 {decision, reasons} or 403 (IP blacklisted)
  GET  /risk/events       → paginated {items, total, page, per_page}  (admin)
  POST /risk/blacklist    → 201 blacklist entry
  GET  /risk/blacklist    → list of active entries
  DELETE /risk/blacklist/<id>         → expire entry
  POST /risk/blacklist/<id>/appeal    → {message, appeal_status}
  PATCH /risk/blacklist/<id>/appeal   → {message, appeal_status}
"""
import uuid


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _register_and_login(client):
    name = f"risk_{uuid.uuid4().hex[:8]}"
    reg = client.post("/auth/register", json={
        "username": name,
        "email": f"{name}@test.com",
        "password": "StrongPass123!XX",
    })
    assert reg.status_code == 201
    uid = reg.get_json()["user_id"]
    login = client.post("/auth/login", json={"username": name, "password": "StrongPass123!XX"})
    assert login.status_code == 200
    return uid, login.get_json()["token"]


# ---------------------------------------------------------------------------
# IP blacklist blocking evaluate
# ---------------------------------------------------------------------------

def test_evaluate_ip_blacklisted_returns_403(client, admin_token):
    """POST /risk/evaluate with blacklisted IP → 403 with message."""
    blocked_ip = "10.99.99.1"
    client.post("/risk/blacklist", json={
        "target_type": "ip", "target_id": blocked_ip, "reason": "test block",
    }, headers=_auth(admin_token))

    resp = client.post("/risk/evaluate", json={
        "event_type": "login", "ip": blocked_ip,
    }, headers=_auth(admin_token))
    assert resp.status_code == 403
    assert "blacklisted" in resp.get_json()["message"].lower()


# ---------------------------------------------------------------------------
# Risk events listing with filters
# ---------------------------------------------------------------------------

def test_risk_events_list_shape(client, admin_token):
    """GET /risk/events returns proper pagination envelope."""
    client.post("/risk/evaluate", json={"event_type": "login", "ip": "1.2.3.4"}, headers=_auth(admin_token))
    resp = client.get("/risk/events", headers=_auth(admin_token))
    assert resp.status_code == 200
    data = resp.get_json()
    for key in ("items", "total", "page", "per_page"):
        assert key in data
    assert data["total"] >= 1


def test_risk_events_filter_by_user_id_returns_matching(client, admin_token):
    """GET /risk/events?user_id=… seeds an event with explicit user_id then verifies filter."""
    me = client.get("/auth/me", headers=_auth(admin_token))
    admin_uid = me.get_json()["user_id"]

    # Admin must provide user_id explicitly for it to be recorded on the event
    client.post("/risk/evaluate", json={
        "event_type": "login", "ip": "2.2.2.2", "user_id": admin_uid,
    }, headers=_auth(admin_token))

    resp = client.get(f"/risk/events?user_id={admin_uid}", headers=_auth(admin_token))
    assert resp.status_code == 200
    items = resp.get_json()["items"]
    assert len(items) >= 1, "expected at least one event for admin user_id"
    for item in items:
        assert item["user_id"] == admin_uid


def test_risk_events_filter_by_ip_returns_matching(client, admin_token):
    """GET /risk/events?ip=… seeds an event then verifies filter."""
    client.post("/risk/evaluate", json={"event_type": "login", "ip": "99.88.77.66"}, headers=_auth(admin_token))
    resp = client.get("/risk/events?ip=99.88.77.66", headers=_auth(admin_token))
    assert resp.status_code == 200
    items = resp.get_json()["items"]
    assert len(items) >= 1, "expected at least one event for seeded IP"
    for item in items:
        assert item["ip"] == "99.88.77.66"


def test_risk_events_filter_by_event_type_returns_matching(client, admin_token):
    """GET /risk/events?event_type=login seeds an event then verifies filter."""
    client.post("/risk/evaluate", json={"event_type": "login", "ip": "3.3.3.3"}, headers=_auth(admin_token))
    resp = client.get("/risk/events?event_type=login", headers=_auth(admin_token))
    assert resp.status_code == 200
    items = resp.get_json()["items"]
    assert len(items) >= 1, "expected at least one login event"
    for item in items:
        assert item["event_type"] == "login"


def test_risk_events_filter_by_decision_returns_matching(client, admin_token):
    """GET /risk/events?decision=allow seeds event then verifies filter."""
    client.post("/risk/evaluate", json={"event_type": "login", "ip": "4.4.4.4"}, headers=_auth(admin_token))
    resp = client.get("/risk/events?decision=allow", headers=_auth(admin_token))
    assert resp.status_code == 200
    items = resp.get_json()["items"]
    assert len(items) >= 1, "expected at least one 'allow' decision"
    for item in items:
        assert item["decision"] == "allow"


def test_risk_events_date_filter(client, admin_token):
    """GET /risk/events with date_from/date_to returns 200."""
    resp = client.get(
        "/risk/events?date_from=2020-01-01T00:00:00&date_to=2099-01-01T00:00:00",
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200


def test_risk_events_bad_date_silently_ignored(client, admin_token):
    """GET /risk/events with invalid date → 200, malformed dates skipped."""
    resp = client.get("/risk/events?date_from=bad-date", headers=_auth(admin_token))
    assert resp.status_code == 200


def test_risk_events_per_page_respected(client, admin_token):
    """GET /risk/events?per_page=5 limits page size."""
    resp = client.get("/risk/events?page=1&per_page=5", headers=_auth(admin_token))
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["per_page"] == 5
    assert len(data["items"]) <= 5


def test_risk_events_non_admin_rejected(client, user_token):
    """GET /risk/events for non-admin → 403."""
    resp = client.get("/risk/events", headers=_auth(user_token))
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Blacklist list
# ---------------------------------------------------------------------------

def test_blacklist_list_returns_array(client, admin_token):
    """GET /risk/blacklist returns list of active entries."""
    resp = client.get("/risk/blacklist", headers=_auth(admin_token))
    assert resp.status_code == 200
    assert isinstance(resp.get_json(), list)


# ---------------------------------------------------------------------------
# Appeal authorization
# ---------------------------------------------------------------------------

def test_appeal_own_user_blacklist_returns_pending(client, admin_token):
    """User blacklisted by user-type can appeal their own entry → pending."""
    uid, tok = _register_and_login(client)
    bl = client.post("/risk/blacklist", json={
        "target_type": "user", "target_id": str(uid), "reason": "test",
    }, headers=_auth(admin_token))
    assert bl.status_code == 201
    bl_id = bl.get_json()["id"]

    resp = client.post(f"/risk/blacklist/{bl_id}/appeal", headers=_auth(tok))
    assert resp.status_code == 200
    assert resp.get_json()["appeal_status"] == "pending"


def test_appeal_other_users_blacklist_returns_403(client, admin_token):
    """User cannot appeal a blacklist entry targeting another user."""
    uid1, _ = _register_and_login(client)
    _, tok2 = _register_and_login(client)

    bl = client.post("/risk/blacklist", json={
        "target_type": "user", "target_id": str(uid1), "reason": "test",
    }, headers=_auth(admin_token))
    bl_id = bl.get_json()["id"]

    resp = client.post(f"/risk/blacklist/{bl_id}/appeal", headers=_auth(tok2))
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "forbidden"


def test_appeal_device_blacklist_non_admin_returns_403(client, admin_token):
    """Regular user cannot appeal device/IP blacklist."""
    _, tok = _register_and_login(client)
    bl = client.post("/risk/blacklist", json={
        "target_type": "device", "target_id": "dev-xyz", "reason": "test",
    }, headers=_auth(admin_token))
    bl_id = bl.get_json()["id"]

    resp = client.post(f"/risk/blacklist/{bl_id}/appeal", headers=_auth(tok))
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "forbidden"


def test_appeal_not_found(client, admin_token):
    """POST /risk/blacklist/999999/appeal → 404."""
    resp = client.post("/risk/blacklist/999999/appeal", headers=_auth(admin_token))
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Non-admin user_id enforcement
# ---------------------------------------------------------------------------

def test_evaluate_non_admin_ignores_user_id(client, user_token):
    """Non-admin POST /risk/evaluate forces user_id to self → 200."""
    resp = client.post("/risk/evaluate", json={
        "event_type": "login", "user_id": 999999,
    }, headers=_auth(user_token))
    assert resp.status_code == 200
    data = resp.get_json()
    assert "decision" in data
    assert "reasons" in data
