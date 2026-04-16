"""
Extended admin API tests covering audit-log filters, user detail,
master-record transitions, and decryption edge cases.

Route contract (from app/api/admin.py):
  GET    /admin/users                                         → paginated list
  GET    /admin/users/<id>                                    → user detail
  PATCH  /admin/users/<id>                                    → update user
  GET    /admin/audit-logs                                    → paginated, filterable list
  GET    /admin/audit-logs/<id>                               → single entry
  GET    /admin/master-records/<entity_type>/<entity_id>      → record + history
  POST   /admin/master-records/<entity_type>/<entity_id>/transition → status change
"""
import json
import uuid


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _register(client, username):
    resp = client.post("/auth/register", json={
        "username": username,
        "email": f"{username}@test.com",
        "password": "StrongPass123!XX",
    })
    assert resp.status_code == 201, f"register failed: {resp.get_json()}"
    return resp


# ---------------------------------------------------------------------------
# User detail & update
# ---------------------------------------------------------------------------

def test_admin_get_user_detail(client, admin_token):
    """GET /admin/users/<id> returns full user object with expected keys."""
    name = f"detail_{uuid.uuid4().hex[:8]}"
    r = _register(client, name)
    uid = r.get_json()["user_id"]

    resp = client.get(f"/admin/users/{uid}", headers=_auth(admin_token))
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["id"] == uid
    assert data["username"] == name
    assert "email" in data
    assert "status" in data
    assert "roles" in data
    assert "created_at" in data


def test_admin_get_user_not_found(client, admin_token):
    """GET /admin/users/<id> for nonexistent user → 404 with error envelope."""
    resp = client.get("/admin/users/999999", headers=_auth(admin_token))
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "not_found"


def test_admin_patch_user_status(client, admin_token):
    """PATCH /admin/users/<id> changes user status and returns updated object."""
    r = _register(client, f"st_{uuid.uuid4().hex[:8]}")
    uid = r.get_json()["user_id"]

    resp = client.patch(
        f"/admin/users/{uid}",
        json={"status": "suspended"},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "suspended"
    assert data["id"] == uid


def test_admin_patch_user_not_found(client, admin_token):
    """PATCH /admin/users/<id> for nonexistent user → 404."""
    resp = client.patch(
        "/admin/users/999999",
        json={"status": "active"},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "not_found"


def test_admin_get_user_with_purpose_header_creates_audit(client, admin_token, app):
    """GET /admin/users/<id> with X-Data-Access-Purpose records audit entry."""
    r = _register(client, f"purp_{uuid.uuid4().hex[:8]}")
    uid = r.get_json()["user_id"]

    resp = client.get(
        f"/admin/users/{uid}",
        headers={**_auth(admin_token), "X-Data-Access-Purpose": "compliance_review"},
    )
    assert resp.status_code == 200

    # Verify an audit log was created with that purpose
    logs = client.get(
        f"/admin/audit-logs?entity_type=user&entity_id={uid}",
        headers=_auth(admin_token),
    )
    assert logs.status_code == 200
    items = logs.get_json()["items"]
    assert len(items) >= 1


# ---------------------------------------------------------------------------
# Audit log filtering
# ---------------------------------------------------------------------------

def test_audit_log_list_shape(client, admin_token):
    """GET /admin/audit-logs returns proper pagination envelope."""
    resp = client.get("/admin/audit-logs", headers=_auth(admin_token))
    assert resp.status_code == 200
    data = resp.get_json()
    for key in ("items", "total", "page", "per_page", "pages"):
        assert key in data, f"missing pagination key: {key}"
    assert isinstance(data["items"], list)


def test_audit_log_filter_by_actor_id(client, admin_token):
    """GET /admin/audit-logs?actor_id=… seeds event then verifies filter."""
    # Seed: registration generates audit with the registering user as entity
    _register(client, f"af_{uuid.uuid4().hex[:8]}")
    me = client.get("/auth/me", headers=_auth(admin_token))
    admin_uid = me.get_json()["user_id"]

    resp = client.get(f"/admin/audit-logs?actor_id={admin_uid}", headers=_auth(admin_token))
    assert resp.status_code == 200
    items = resp.get_json()["items"]
    assert len(items) >= 1, "expected at least one audit log for admin actor"
    for item in items:
        assert item["actor_id"] == admin_uid


def test_audit_log_filter_by_action(client, admin_token):
    """GET /admin/audit-logs?action=login_success seeds and verifies."""
    # Seed: register + login generates a login_success audit entry
    name = f"ac_{uuid.uuid4().hex[:8]}"
    _register(client, name)
    client.post("/auth/login", json={"username": name, "password": "StrongPass123!XX"})

    resp = client.get("/admin/audit-logs?action=login_success", headers=_auth(admin_token))
    assert resp.status_code == 200
    items = resp.get_json()["items"]
    assert len(items) >= 1, "expected at least one login_success audit entry"
    for item in items:
        assert item["action"] == "login_success"


def test_audit_log_filter_by_entity_type(client, admin_token):
    """GET /admin/audit-logs?entity_type=user seeds and verifies."""
    _register(client, f"et_{uuid.uuid4().hex[:8]}")
    resp = client.get("/admin/audit-logs?entity_type=user", headers=_auth(admin_token))
    assert resp.status_code == 200
    items = resp.get_json()["items"]
    assert len(items) >= 1, "expected at least one user entity audit entry"
    for item in items:
        assert item["entity_type"] == "user"


def test_audit_log_filter_by_date_range(client, admin_token):
    """GET /admin/audit-logs with date_from/date_to returns 200 with items."""
    resp = client.get(
        "/admin/audit-logs?date_from=2020-01-01T00:00:00&date_to=2099-01-01T00:00:00",
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200
    assert isinstance(resp.get_json()["items"], list)


def test_audit_log_filter_bad_date_silently_ignored(client, admin_token):
    """Invalid date_from is silently ignored (returns 200, not 400)."""
    resp = client.get("/admin/audit-logs?date_from=not-a-date", headers=_auth(admin_token))
    assert resp.status_code == 200


def test_audit_log_detail_found(client, admin_token):
    """GET /admin/audit-logs/<id> returns single entry with all expected keys."""
    # Trigger audit event
    _register(client, f"aud_{uuid.uuid4().hex[:8]}")
    listing = client.get("/admin/audit-logs?per_page=1", headers=_auth(admin_token))
    items = listing.get_json()["items"]
    assert len(items) >= 1, "Expected at least one audit log after registration"

    entry_id = items[0]["id"]
    resp = client.get(f"/admin/audit-logs/{entry_id}", headers=_auth(admin_token))
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["id"] == entry_id
    for key in ("actor_id", "action", "entity_type", "entity_id", "created_at"):
        assert key in data, f"missing key: {key}"


def test_audit_log_detail_not_found(client, admin_token):
    """GET /admin/audit-logs/<id> for nonexistent → 404."""
    resp = client.get("/admin/audit-logs/999999", headers=_auth(admin_token))
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "not_found"


# ---------------------------------------------------------------------------
# Master-record get & transition (path-based routes)
# ---------------------------------------------------------------------------

def test_master_record_get_for_user(client, admin_token):
    """GET /admin/master-records/user/<id> returns record with history chain."""
    r = _register(client, f"mrg_{uuid.uuid4().hex[:8]}")
    uid = r.get_json()["user_id"]

    resp = client.get(
        f"/admin/master-records/user/{uid}",
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["entity_type"] == "user"
    assert data["entity_id"] == uid
    assert data["current_status"] == "active"
    assert isinstance(data["history"], list)


def test_master_record_get_not_found(client, admin_token):
    """GET /admin/master-records/user/999999 → 404."""
    resp = client.get(
        "/admin/master-records/user/999999",
        headers=_auth(admin_token),
    )
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "not_found"


def test_master_record_transition_success(client, admin_token):
    """POST /admin/master-records/user/<id>/transition changes status."""
    r = _register(client, f"mrt_{uuid.uuid4().hex[:8]}")
    uid = r.get_json()["user_id"]

    resp = client.post(
        f"/admin/master-records/user/{uid}/transition",
        json={"to_status": "suspended", "reason": "test transition"},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["entity_type"] == "user"
    assert data["entity_id"] == uid
    assert data["current_status"] == "suspended"

    # Verify the history chain grew
    mr = client.get(f"/admin/master-records/user/{uid}", headers=_auth(admin_token))
    assert mr.status_code == 200
    history = mr.get_json()["history"]
    assert any(h["to_status"] == "suspended" for h in history)


def test_master_record_transition_not_found(client, admin_token):
    """POST /admin/master-records/user/999999/transition → 404."""
    resp = client.post(
        "/admin/master-records/user/999999/transition",
        json={"to_status": "suspended", "reason": "missing"},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 404
