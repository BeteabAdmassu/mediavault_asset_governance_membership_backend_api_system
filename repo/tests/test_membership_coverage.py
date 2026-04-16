"""
Extended membership tests covering tier creation edge cases, ledger
credit/debit paths, balance checks, and IDOR scenarios.

Route contract (from app/api/membership.py):
  POST  /membership/tiers         → 201 {id, name, min_points, …}
  PATCH /membership/tiers/<id>    → 200 updated tier
  GET   /membership/me            → 200 {user_id, tier_id, tier_name, points_balance, …}
  POST  /membership/ledger/credit → 201 {id, user_id, amount, currency, entry_type, …}
  POST  /membership/ledger/debit  → 201 (same shape)
  GET   /membership/ledger        → 200 paginated  (admin, requires user_id)
  GET   /membership/ledger/me     → 200 paginated  (own)
"""
import uuid


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _unique():
    return uuid.uuid4().hex[:8]


# ---------------------------------------------------------------------------
# Tier CRUD
# ---------------------------------------------------------------------------

def test_create_tier_duplicate_name_returns_409(client, admin_token):
    """POST /membership/tiers with duplicate name → 409 conflict."""
    name = f"Tier_{_unique()}"
    first = client.post("/membership/tiers", json={"name": name, "min_points": 0}, headers=_auth(admin_token))
    assert first.status_code == 201

    resp = client.post("/membership/tiers", json={"name": name, "min_points": 100}, headers=_auth(admin_token))
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "conflict"


def test_update_tier_persists(client, admin_token):
    """PATCH /membership/tiers/<id> persists the change."""
    cr = client.post(
        "/membership/tiers",
        json={"name": f"Tier_{_unique()}", "min_points": 50},
        headers=_auth(admin_token),
    )
    assert cr.status_code == 201
    tid = cr.get_json()["id"]

    resp = client.patch(f"/membership/tiers/{tid}", json={"min_points": 75}, headers=_auth(admin_token))
    assert resp.status_code == 200
    assert resp.get_json()["min_points"] == 75
    assert resp.get_json()["id"] == tid


def test_update_tier_not_found(client, admin_token):
    """PATCH /membership/tiers/999999 → 404."""
    resp = client.patch("/membership/tiers/999999", json={"min_points": 100}, headers=_auth(admin_token))
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Ledger credit
# ---------------------------------------------------------------------------

def test_ledger_credit_returns_full_entry(client, admin_token):
    """POST /membership/ledger/credit → 201 with entry details."""
    key = f"cr_{_unique()}"
    resp = client.post("/membership/ledger/credit", json={
        "user_id": 1, "amount": 500, "currency": "points",
        "reason": "bonus", "idempotency_key": key,
    }, headers=_auth(admin_token))
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["amount"] == 500
    assert data["currency"] == "points"
    assert data["entry_type"] == "credit"
    assert data["idempotency_key"] == key


def test_ledger_credit_idempotency_conflict(client, admin_token):
    """POST /membership/ledger/credit with duplicate key → 409."""
    key = f"cr_{_unique()}"
    client.post("/membership/ledger/credit", json={
        "user_id": 1, "amount": 100, "currency": "points",
        "reason": "first", "idempotency_key": key,
    }, headers=_auth(admin_token))
    resp = client.post("/membership/ledger/credit", json={
        "user_id": 1, "amount": 200, "currency": "points",
        "reason": "second", "idempotency_key": key,
    }, headers=_auth(admin_token))
    assert resp.status_code == 409


def test_ledger_credit_zero_amount_returns_422(client, admin_token):
    """POST /membership/ledger/credit with amount=0 → 422."""
    resp = client.post("/membership/ledger/credit", json={
        "user_id": 1, "amount": 0, "currency": "points",
        "reason": "zero", "idempotency_key": f"cr_{_unique()}",
    }, headers=_auth(admin_token))
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Ledger debit
# ---------------------------------------------------------------------------

def test_ledger_debit_returns_full_entry(client, admin_token):
    """POST /membership/ledger/debit with sufficient balance → 201."""
    # Seed balance
    client.post("/membership/ledger/credit", json={
        "user_id": 1, "amount": 5000, "currency": "points",
        "reason": "seed", "idempotency_key": f"seed_{_unique()}",
    }, headers=_auth(admin_token))

    key = f"db_{_unique()}"
    resp = client.post("/membership/ledger/debit", json={
        "user_id": 1, "amount": 100, "currency": "points",
        "reason": "purchase", "idempotency_key": key,
    }, headers=_auth(admin_token))
    assert resp.status_code == 201
    data = resp.get_json()
    # Debit entries store amount as negative in the ledger
    assert data["amount"] == -100
    assert data["entry_type"] == "debit"


def test_ledger_debit_insufficient_balance_returns_422(client, admin_token):
    """POST /membership/ledger/debit exceeding balance → 422."""
    reg = client.post("/auth/register", json={
        "username": f"broke_{_unique()}", "email": f"broke_{_unique()}@t.com",
        "password": "StrongPass123!XX",
    })
    uid = reg.get_json()["user_id"]

    resp = client.post("/membership/ledger/debit", json={
        "user_id": uid, "amount": 999999, "currency": "points",
        "reason": "overspend", "idempotency_key": f"db_{_unique()}",
    }, headers=_auth(admin_token))
    assert resp.status_code == 422


def test_ledger_debit_idempotency_conflict(client, admin_token):
    """POST /membership/ledger/debit with duplicate key → 409."""
    client.post("/membership/ledger/credit", json={
        "user_id": 1, "amount": 500, "currency": "points",
        "reason": "seed", "idempotency_key": f"seed_{_unique()}",
    }, headers=_auth(admin_token))

    key = f"db_{_unique()}"
    client.post("/membership/ledger/debit", json={
        "user_id": 1, "amount": 10, "currency": "points",
        "reason": "first", "idempotency_key": key,
    }, headers=_auth(admin_token))
    resp = client.post("/membership/ledger/debit", json={
        "user_id": 1, "amount": 10, "currency": "points",
        "reason": "dupe", "idempotency_key": key,
    }, headers=_auth(admin_token))
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Ledger admin listing
# ---------------------------------------------------------------------------

def test_ledger_admin_missing_user_id_returns_400(client, admin_token):
    """GET /membership/ledger without user_id → 400."""
    resp = client.get("/membership/ledger", headers=_auth(admin_token))
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "bad_request"


def test_ledger_admin_with_user_id_returns_paginated(client, admin_token):
    """GET /membership/ledger?user_id=1 → 200 with pagination keys."""
    resp = client.get("/membership/ledger?user_id=1", headers=_auth(admin_token))
    assert resp.status_code == 200
    data = resp.get_json()
    for key in ("items", "total", "page", "per_page"):
        assert key in data


# ---------------------------------------------------------------------------
# Membership me
# ---------------------------------------------------------------------------

def test_membership_me_returns_user_balance(client, user_token):
    """GET /membership/me returns membership with expected keys."""
    resp = client.get("/membership/me", headers=_auth(user_token))
    assert resp.status_code == 200
    data = resp.get_json()
    for key in ("user_id", "tier_id", "points_balance", "stored_value_balance"):
        assert key in data


# ---------------------------------------------------------------------------
# IDOR - ledger/me user_id mismatch
# ---------------------------------------------------------------------------

def test_ledger_me_idor_rejected(client, user_token):
    """GET /membership/ledger/me?user_id=<other> for non-admin → 403."""
    resp = client.get("/membership/ledger/me?user_id=999", headers=_auth(user_token))
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "forbidden"
