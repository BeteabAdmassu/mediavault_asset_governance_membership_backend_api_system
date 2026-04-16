"""
Extended marketing/coupon tests covering campaign CRUD, coupon detail,
coupon creation conflicts, and redemption edge cases.

Route contract (from app/api/marketing.py):
  POST   /marketing/campaigns           → 201 with id, name, type, …
  GET    /marketing/campaigns           → paginated {items, total, page, …}
  GET    /marketing/campaigns/<id>      → single campaign
  PATCH  /marketing/campaigns/<id>      → updated campaign
  DELETE /marketing/campaigns/<id>      → {message}
  POST   /marketing/coupons             → 201 with id, code, campaign_id, …
  GET    /marketing/coupons             → paginated
  GET    /marketing/coupons/<id>        → single coupon
"""
import uuid


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _create_campaign(client, admin_token, **overrides):
    payload = {
        "name": f"Camp_{uuid.uuid4().hex[:8]}",
        "type": "promotion",
        "start_at": "2026-01-01T00:00:00",
        "end_at": "2099-12-31T23:59:59",
        "benefit_type": "percentage",
        "benefit_value": 10,
        "max_redemptions": 100,
        "per_user_cap": 2,
        "min_order_cents": 1000,
    }
    payload.update(overrides)
    resp = client.post("/marketing/campaigns", json=payload, headers=_auth(admin_token))
    assert resp.status_code == 201, f"campaign create failed: {resp.get_json()}"
    return resp


def _create_coupon(client, admin_token, campaign_id, **overrides):
    payload = {
        "code": f"C_{uuid.uuid4().hex[:8]}",
        "campaign_id": campaign_id,
    }
    payload.update(overrides)
    return client.post("/marketing/coupons", json=payload, headers=_auth(admin_token))


# ---------------------------------------------------------------------------
# Campaign CRUD
# ---------------------------------------------------------------------------

def test_campaign_create_returns_full_object(client, admin_token):
    """POST /marketing/campaigns → 201 with all expected keys."""
    resp = _create_campaign(client, admin_token)
    data = resp.get_json()
    for key in ("id", "name", "type", "benefit_type", "benefit_value", "created_at"):
        assert key in data, f"missing key: {key}"
    assert data["benefit_type"] == "percentage"
    assert data["benefit_value"] == 10


def test_campaign_list_pagination_shape(client, admin_token):
    """GET /marketing/campaigns returns proper pagination envelope."""
    _create_campaign(client, admin_token)
    resp = client.get("/marketing/campaigns", headers=_auth(admin_token))
    assert resp.status_code == 200
    data = resp.get_json()
    for key in ("items", "total", "page", "per_page", "pages"):
        assert key in data, f"missing pagination key: {key}"
    assert isinstance(data["items"], list)
    assert data["total"] >= 1


def test_campaign_detail(client, admin_token):
    """GET /marketing/campaigns/<id> returns matching campaign."""
    cr = _create_campaign(client, admin_token)
    cid = cr.get_json()["id"]
    resp = client.get(f"/marketing/campaigns/{cid}", headers=_auth(admin_token))
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["id"] == cid
    assert data["benefit_type"] == "percentage"


def test_campaign_detail_not_found(client, admin_token):
    """GET /marketing/campaigns/999999 → 404."""
    resp = client.get("/marketing/campaigns/999999", headers=_auth(admin_token))
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "not_found"


def test_campaign_update(client, admin_token):
    """PATCH /marketing/campaigns/<id> persists the change."""
    cr = _create_campaign(client, admin_token)
    cid = cr.get_json()["id"]
    resp = client.patch(
        f"/marketing/campaigns/{cid}",
        json={"name": "Updated Campaign"},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["name"] == "Updated Campaign"
    assert data["id"] == cid

    # Verify persistence via GET
    get_resp = client.get(f"/marketing/campaigns/{cid}", headers=_auth(admin_token))
    assert get_resp.get_json()["name"] == "Updated Campaign"


def test_campaign_update_not_found(client, admin_token):
    """PATCH /marketing/campaigns/999999 → 404."""
    resp = client.patch(
        "/marketing/campaigns/999999",
        json={"name": "Nope"},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 404


def test_campaign_delete_and_verify_gone(client, admin_token):
    """DELETE /marketing/campaigns/<id> soft-deletes; subsequent GET → 404."""
    cr = _create_campaign(client, admin_token)
    cid = cr.get_json()["id"]
    resp = client.delete(f"/marketing/campaigns/{cid}", headers=_auth(admin_token))
    assert resp.status_code == 200
    assert "message" in resp.get_json()

    resp2 = client.get(f"/marketing/campaigns/{cid}", headers=_auth(admin_token))
    assert resp2.status_code == 404


def test_campaign_delete_not_found(client, admin_token):
    """DELETE /marketing/campaigns/999999 → 404."""
    resp = client.delete("/marketing/campaigns/999999", headers=_auth(admin_token))
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Coupon CRUD
# ---------------------------------------------------------------------------

def test_coupon_create_returns_full_object(client, admin_token):
    """POST /marketing/coupons → 201 with expected keys."""
    cr = _create_campaign(client, admin_token)
    cid = cr.get_json()["id"]
    code = f"CPN_{uuid.uuid4().hex[:8]}"
    resp = _create_coupon(client, admin_token, cid, code=code)
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["code"] == code
    assert data["campaign_id"] == cid
    assert "id" in data


def test_coupon_list_pagination_shape(client, admin_token):
    """GET /marketing/coupons returns proper pagination envelope."""
    cr = _create_campaign(client, admin_token)
    cid = cr.get_json()["id"]
    _create_coupon(client, admin_token, cid)
    resp = client.get("/marketing/coupons", headers=_auth(admin_token))
    assert resp.status_code == 200
    data = resp.get_json()
    for key in ("items", "total", "page", "per_page"):
        assert key in data


def test_coupon_detail(client, admin_token):
    """GET /marketing/coupons/<id> returns matching coupon."""
    cr = _create_campaign(client, admin_token)
    cid = cr.get_json()["id"]
    coupon_resp = _create_coupon(client, admin_token, cid)
    coupon_id = coupon_resp.get_json()["id"]
    resp = client.get(f"/marketing/coupons/{coupon_id}", headers=_auth(admin_token))
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["id"] == coupon_id
    assert data["campaign_id"] == cid


def test_coupon_detail_not_found(client, admin_token):
    """GET /marketing/coupons/999999 → 404."""
    resp = client.get("/marketing/coupons/999999", headers=_auth(admin_token))
    assert resp.status_code == 404


def test_coupon_create_duplicate_code_returns_409(client, admin_token):
    """POST /marketing/coupons with duplicate code → 409 conflict."""
    cr = _create_campaign(client, admin_token)
    cid = cr.get_json()["id"]
    code = f"DUP_{uuid.uuid4().hex[:8]}"
    first = _create_coupon(client, admin_token, cid, code=code)
    assert first.status_code == 201

    second = _create_coupon(client, admin_token, cid, code=code)
    assert second.status_code == 409
    assert second.get_json()["error"] == "conflict"


def test_coupon_create_campaign_not_found_returns_404(client, admin_token):
    """POST /marketing/coupons with nonexistent campaign_id → 404."""
    resp = client.post(
        "/marketing/coupons",
        json={"code": f"NF_{uuid.uuid4().hex[:8]}", "campaign_id": 999999},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 404
