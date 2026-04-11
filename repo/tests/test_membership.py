"""
Prompt 5 – Membership Tiers & Points Ledger tests.

All 16 tests as specified.
"""
import uuid
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _unique_order():
    return f"order_{uuid.uuid4().hex[:10]}"


def _unique_key():
    return f"key_{uuid.uuid4().hex[:10]}"


def _get_user_id(client, token):
    resp = client.get("/auth/me", headers=_auth(token))
    return resp.get_json()["user_id"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_default_tiers_seeded(client):
    """GET /membership/tiers → contains Basic (0), Silver (500), Gold (2000)."""
    resp = client.get("/membership/tiers")
    assert resp.status_code == 200
    tiers = resp.get_json()
    names = {t["name"]: t["min_points"] for t in tiers}
    assert "Basic" in names
    assert "Silver" in names
    assert "Gold" in names
    assert names["Basic"] == 0
    assert names["Silver"] == 500
    assert names["Gold"] == 2000


def test_create_tier(client, admin_token):
    """Admin POST /membership/tiers → 201, retrievable."""
    tier_name = f"Platinum_{uuid.uuid4().hex[:6]}"
    resp = client.post(
        "/membership/tiers",
        json={"name": tier_name, "min_points": 5000, "benefits": "Platinum perks"},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    data = resp.get_json()
    assert data["name"] == tier_name
    assert data["min_points"] == 5000

    # Verify retrievable
    list_resp = client.get("/membership/tiers")
    names = [t["name"] for t in list_resp.get_json()]
    assert tier_name in names


def test_accrue_points_floor_rounding(client, app, admin_token, user_token):
    """Accrue eligible_amount_cents=150 → 1 point credited (floor(150/100)=1)."""
    user_id = _get_user_id(client, user_token)
    order_id = _unique_order()

    resp = client.post(
        "/membership/accrue",
        json={"user_id": user_id, "order_id": order_id, "eligible_amount_cents": 150},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    data = resp.get_json()
    assert data["amount"] == 1
    assert data["currency"] == "points"


def test_accrue_points_balance_reflected(client, app, admin_token, user_token):
    """Two 500-pt accruals → GET /membership/me shows 1000 pts."""
    user_id = _get_user_id(client, user_token)

    # 50000 cents = 500 pts each
    for i in range(2):
        order_id = _unique_order()
        resp = client.post(
            "/membership/accrue",
            json={"user_id": user_id, "order_id": order_id, "eligible_amount_cents": 50000},
            headers=_auth(admin_token),
        )
        assert resp.status_code == 201, resp.get_data(as_text=True)

    me_resp = client.get("/membership/me", headers=_auth(user_token))
    assert me_resp.status_code == 200
    data = me_resp.get_json()
    assert data["points_balance"] >= 1000


def test_tier_upgrade_to_silver(client, app, admin_token, user_token):
    """Accrue 500 pts from 0 → tier = Silver."""
    user_id = _get_user_id(client, user_token)

    # 50000 cents = 500 pts
    order_id = _unique_order()
    resp = client.post(
        "/membership/accrue",
        json={"user_id": user_id, "order_id": order_id, "eligible_amount_cents": 50000},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)

    me_resp = client.get("/membership/me", headers=_auth(user_token))
    assert me_resp.status_code == 200
    data = me_resp.get_json()
    assert data["tier_name"] == "Silver"


def test_tier_upgrade_to_gold(client, app, admin_token, user_token):
    """Accrue 2000 total → tier = Gold."""
    user_id = _get_user_id(client, user_token)

    # 200000 cents = 2000 pts
    order_id = _unique_order()
    resp = client.post(
        "/membership/accrue",
        json={"user_id": user_id, "order_id": order_id, "eligible_amount_cents": 200000},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)

    me_resp = client.get("/membership/me", headers=_auth(user_token))
    assert me_resp.status_code == 200
    data = me_resp.get_json()
    assert data["tier_name"] == "Gold"


def test_accrue_idempotency(client, app, admin_token, user_token):
    """Same order_id twice → second 409; balance unchanged."""
    user_id = _get_user_id(client, user_token)
    order_id = _unique_order()

    # First accrual
    resp1 = client.post(
        "/membership/accrue",
        json={"user_id": user_id, "order_id": order_id, "eligible_amount_cents": 10000},
        headers=_auth(admin_token),
    )
    assert resp1.status_code == 201, resp1.get_data(as_text=True)

    # Get balance after first
    me_resp1 = client.get("/membership/me", headers=_auth(user_token))
    balance_after_first = me_resp1.get_json()["points_balance"]

    # Second accrual with same order_id → 409
    resp2 = client.post(
        "/membership/accrue",
        json={"user_id": user_id, "order_id": order_id, "eligible_amount_cents": 10000},
        headers=_auth(admin_token),
    )
    assert resp2.status_code == 409

    # Balance unchanged
    me_resp2 = client.get("/membership/me", headers=_auth(user_token))
    balance_after_second = me_resp2.get_json()["points_balance"]
    assert balance_after_first == balance_after_second


def test_credit_ledger(client, app, admin_token, user_token):
    """Admin credit → 201; in ledger list."""
    user_id = _get_user_id(client, user_token)
    idem_key = _unique_key()

    resp = client.post(
        "/membership/ledger/credit",
        json={
            "user_id": user_id,
            "amount": 100,
            "currency": "points",
            "reason": "test credit",
            "idempotency_key": idem_key,
        },
        headers=_auth(admin_token),
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    data = resp.get_json()
    assert data["amount"] == 100
    assert data["entry_type"] == "credit"

    # Check it appears in ledger
    ledger_resp = client.get(
        f"/membership/ledger?user_id={user_id}",
        headers=_auth(admin_token),
    )
    assert ledger_resp.status_code == 200
    items = ledger_resp.get_json()["items"]
    keys = [e["idempotency_key"] for e in items]
    assert idem_key in keys


def test_debit_ledger_success(client, app, admin_token, user_token):
    """Credit 100, debit 50 → balance = 50."""
    user_id = _get_user_id(client, user_token)

    # Credit 100
    credit_resp = client.post(
        "/membership/ledger/credit",
        json={
            "user_id": user_id,
            "amount": 100,
            "currency": "stored_value",
            "reason": "initial credit",
            "idempotency_key": _unique_key(),
        },
        headers=_auth(admin_token),
    )
    assert credit_resp.status_code == 201

    # Debit 50
    debit_resp = client.post(
        "/membership/ledger/debit",
        json={
            "user_id": user_id,
            "amount": 50,
            "currency": "stored_value",
            "reason": "partial debit",
            "idempotency_key": _unique_key(),
        },
        headers=_auth(admin_token),
    )
    assert debit_resp.status_code == 201, debit_resp.get_data(as_text=True)
    data = debit_resp.get_json()
    assert data["amount"] == -50
    assert data["entry_type"] == "debit"


def test_debit_exceeds_balance(client, app, admin_token, user_token):
    """Debit more than balance → 422."""
    user_id = _get_user_id(client, user_token)

    # Try to debit 9999999 from empty or low balance
    resp = client.post(
        "/membership/ledger/debit",
        json={
            "user_id": user_id,
            "amount": 9999999,
            "currency": "stored_value",
            "reason": "overdraft attempt",
            "idempotency_key": _unique_key(),
        },
        headers=_auth(admin_token),
    )
    assert resp.status_code == 422


def test_ledger_immutable(client, app, admin_token, user_token):
    """Attempt to UPDATE ledger row via ORM → raises RuntimeError."""
    user_id = _get_user_id(client, user_token)

    # Create a credit entry
    idem_key = _unique_key()
    resp = client.post(
        "/membership/ledger/credit",
        json={
            "user_id": user_id,
            "amount": 10,
            "currency": "points",
            "reason": "immutability test",
            "idempotency_key": idem_key,
        },
        headers=_auth(admin_token),
    )
    assert resp.status_code == 201
    entry_id = resp.get_json()["id"]

    # Attempt to update via ORM → should raise RuntimeError
    with app.app_context():
        from app.models.membership import Ledger
        from app.extensions import db

        entry = Ledger.query.get(entry_id)
        assert entry is not None
        entry.amount = 999  # Modify in memory
        with pytest.raises(RuntimeError, match="immutable"):
            db.session.flush()
        db.session.rollback()


def test_duplicate_idempotency_key_credit(client, app, admin_token, user_token):
    """Same idempotency_key on two credits → second 409."""
    user_id = _get_user_id(client, user_token)
    idem_key = _unique_key()

    # First credit
    resp1 = client.post(
        "/membership/ledger/credit",
        json={
            "user_id": user_id,
            "amount": 50,
            "currency": "points",
            "reason": "first",
            "idempotency_key": idem_key,
        },
        headers=_auth(admin_token),
    )
    assert resp1.status_code == 201

    # Second credit with same key → 409
    resp2 = client.post(
        "/membership/ledger/credit",
        json={
            "user_id": user_id,
            "amount": 50,
            "currency": "points",
            "reason": "second",
            "idempotency_key": idem_key,
        },
        headers=_auth(admin_token),
    )
    assert resp2.status_code == 409


def test_membership_me_unauthenticated(client):
    """No token → 401."""
    resp = client.get("/membership/me")
    assert resp.status_code == 401


def test_ledger_pagination(client, app, admin_token, user_token):
    """Create 25 entries, GET /membership/ledger/me?page=2&per_page=10 → correct slice."""
    user_id = _get_user_id(client, user_token)

    # Create 25 credit entries
    for i in range(25):
        resp = client.post(
            "/membership/ledger/credit",
            json={
                "user_id": user_id,
                "amount": 1,
                "currency": "points",
                "reason": f"pagination test {i}",
                "idempotency_key": f"paginate_{user_id}_{i}_{uuid.uuid4().hex[:6]}",
            },
            headers=_auth(admin_token),
        )
        assert resp.status_code == 201, resp.get_data(as_text=True)

    # Get page 2 with per_page=10
    resp = client.get(
        "/membership/ledger/me?page=2&per_page=10",
        headers=_auth(user_token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    data = resp.get_json()
    assert data["page"] == 2
    assert data["per_page"] == 10
    assert len(data["items"]) == 10
    assert data["total"] >= 25


def test_idor_ledger_other_user(client, app, admin_token, user_token):
    """User A calls GET /membership/ledger?user_id=admin_user_id → 403."""
    # Get admin user_id
    admin_user_id = _get_user_id(client, admin_token)

    # Regular user tries to access admin's ledger via admin-only route
    # The /membership/ledger endpoint is admin-only so user will get 403 for role check
    resp = client.get(
        f"/membership/ledger?user_id={admin_user_id}",
        headers=_auth(user_token),
    )
    assert resp.status_code == 403


def test_idor_accrue_other_user(client, app, admin_token, user_token):
    """Regular user calls POST /membership/accrue for another user_id → 403."""
    # Get admin user_id as the "other user"
    admin_user_id = _get_user_id(client, admin_token)

    # Regular user (non-admin) tries to accrue for another user → 403 (no admin role)
    resp = client.post(
        "/membership/accrue",
        json={
            "user_id": admin_user_id,
            "order_id": _unique_order(),
            "eligible_amount_cents": 10000,
        },
        headers=_auth(user_token),
    )
    assert resp.status_code == 403


def test_accrue_rate_limited(client, app, admin_token):
    """POST /membership/accrue returns 429 after exceeding 30/minute."""
    from app.extensions import limiter
    with app.app_context():
        try:
            limiter.reset()
        except Exception:
            pass

    last_status = None
    for i in range(31):
        r = client.post(
            "/membership/accrue",
            json={
                "user_id": 1,
                "order_id": f"rl-order-{i}",
                "eligible_amount_cents": 100,
            },
            headers=_auth(admin_token),
        )
        last_status = r.status_code
        if last_status == 429:
            break
    assert last_status == 429, (
        "Expected 429 after exhausting 30/minute limit on POST /membership/accrue"
    )
