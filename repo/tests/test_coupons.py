"""
Tests for Prompt 6: Coupons, Campaigns & Incentive Validation.
"""
import pytest
from datetime import datetime, timezone, timedelta


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now():
    return datetime.now(timezone.utc)


def _campaign_payload(
    name="Test Campaign",
    benefit_type="percent_off",
    benefit_value=10,
    max_redemptions=None,
    per_user_cap=None,
    min_order_cents=None,
    start_offset_days=-1,
    end_offset_days=30,
):
    now = _now()
    payload = {
        "name": name,
        "type": "discount",
        "start_at": (now + timedelta(days=start_offset_days)).isoformat(),
        "end_at": (now + timedelta(days=end_offset_days)).isoformat(),
        "benefit_type": benefit_type,
        "benefit_value": benefit_value,
    }
    if max_redemptions is not None:
        payload["max_redemptions"] = max_redemptions
    if per_user_cap is not None:
        payload["per_user_cap"] = per_user_cap
    if min_order_cents is not None:
        payload["min_order_cents"] = min_order_cents
    return payload


def _create_campaign(client, admin_token, **kwargs):
    resp = client.post(
        "/marketing/campaigns",
        json=_campaign_payload(**kwargs),
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201, f"Campaign creation failed: {resp.get_json()}"
    return resp.get_json()


def _create_coupon(client, admin_token, code, campaign_id, **kwargs):
    payload = {"code": code, "campaign_id": campaign_id}
    payload.update(kwargs)
    resp = client.post(
        "/marketing/coupons",
        json=payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201, f"Coupon creation failed: {resp.get_json()}"
    return resp.get_json()


def _get_user_id(client, token):
    """Get the user_id for a given token by hitting an auth'd endpoint."""
    resp = client.get(
        "/membership/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    data = resp.get_json()
    return data["user_id"]


def _get_admin_id(client, admin_token):
    return _get_user_id(client, admin_token)


def _validate(client, token, user_id, order_id, order_cents, coupon_codes):
    return client.post(
        "/marketing/validate-incentives",
        json={
            "user_id": user_id,
            "order_id": order_id,
            "order_cents": order_cents,
            "coupon_codes": coupon_codes,
        },
        headers={"Authorization": f"Bearer {token}"},
    )


def _redeem(client, token, user_id, order_id, coupon_codes):
    return client.post(
        "/marketing/redeem",
        json={
            "user_id": user_id,
            "order_id": order_id,
            "coupon_codes": coupon_codes,
        },
        headers={"Authorization": f"Bearer {token}"},
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_create_campaign(client, admin_token):
    """Admin can create a campaign."""
    resp = client.post(
        "/marketing/campaigns",
        json=_campaign_payload(name="Summer Sale", benefit_type="percent_off", benefit_value=20),
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["name"] == "Summer Sale"
    assert data["benefit_type"] == "percent_off"
    assert data["benefit_value"] == 20
    assert data["id"] is not None


def test_create_coupon(client, admin_token):
    """Admin can create a coupon linked to a campaign."""
    campaign = _create_campaign(client, admin_token, name="Coupon Campaign")
    resp = client.post(
        "/marketing/coupons",
        json={"code": "TESTCODE10", "campaign_id": campaign["id"]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["code"] == "TESTCODE10"
    assert data["campaign_id"] == campaign["id"]


def test_validate_single_valid_coupon(client, admin_token, user_token):
    """A single valid coupon returns correct discount."""
    campaign = _create_campaign(
        client, admin_token,
        name="Single Valid",
        benefit_type="percent_off",
        benefit_value=10,
    )
    coupon = _create_coupon(client, admin_token, "VALID10", campaign["id"])
    user_id = _get_user_id(client, user_token)

    resp = _validate(client, user_token, user_id, "order-001", 1000, ["VALID10"])
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_discount_cents"] == 100  # 10% of 1000
    assert len(data["discounts"]) == 1
    assert data["discounts"][0]["code"] == "VALID10"
    assert data["discounts"][0]["discount_cents"] == 100


def test_validate_two_compatible_coupons(client, admin_token, user_token):
    """Two coupons with different benefit types both validate successfully."""
    campaign1 = _create_campaign(
        client, admin_token,
        name="Compat Campaign 1",
        benefit_type="percent_off",
        benefit_value=10,
    )
    campaign2 = _create_campaign(
        client, admin_token,
        name="Compat Campaign 2",
        benefit_type="fixed_off",
        benefit_value=50,
    )
    coupon1 = _create_coupon(client, admin_token, "COMPAT10PCT", campaign1["id"])
    coupon2 = _create_coupon(client, admin_token, "COMPAT50OFF", campaign2["id"])
    user_id = _get_user_id(client, user_token)

    resp = _validate(client, user_token, user_id, "order-002", 1000, ["COMPAT10PCT", "COMPAT50OFF"])
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["discounts"]) == 2
    # percent_off: 10% of 1000 = 100, fixed_off: min(50, 1000) = 50
    assert data["total_discount_cents"] == 150


def test_stacking_limit_exceeded(client, admin_token, user_token):
    """More than 2 coupons returns 422."""
    campaign = _create_campaign(client, admin_token, name="Stack Limit Campaign")
    coupon1 = _create_coupon(client, admin_token, "STACK1", campaign["id"])
    coupon2 = _create_coupon(client, admin_token, "STACK2", campaign["id"])
    coupon3 = _create_coupon(client, admin_token, "STACK3", campaign["id"])
    user_id = _get_user_id(client, user_token)

    resp = _validate(client, user_token, user_id, "order-003", 1000, ["STACK1", "STACK2", "STACK3"])
    assert resp.status_code == 422
    data = resp.get_json()
    assert data["error"] == "validation_error"


def test_conflict_same_benefit_type(client, admin_token, user_token):
    """Two coupons from campaigns with same benefit_type returns 422."""
    campaign1 = _create_campaign(
        client, admin_token,
        name="Conflict Campaign 1",
        benefit_type="percent_off",
        benefit_value=10,
    )
    campaign2 = _create_campaign(
        client, admin_token,
        name="Conflict Campaign 2",
        benefit_type="percent_off",
        benefit_value=5,
    )
    coupon1 = _create_coupon(client, admin_token, "CONFLICT10", campaign1["id"])
    coupon2 = _create_coupon(client, admin_token, "CONFLICT5", campaign2["id"])
    user_id = _get_user_id(client, user_token)

    resp = _validate(client, user_token, user_id, "order-004", 1000, ["CONFLICT10", "CONFLICT5"])
    assert resp.status_code == 422
    data = resp.get_json()
    assert data["error"] == "validation_error"
    # Details should indicate benefit_type conflict
    assert any(d.get("error") == "benefit_type_conflict" for d in data.get("details", []))


def test_expired_coupon_rejected(client, admin_token, user_token):
    """Coupon with expires_at in the past returns 422."""
    campaign = _create_campaign(client, admin_token, name="Expired Coupon Campaign")
    past = (_now() - timedelta(days=1)).isoformat()
    coupon = _create_coupon(
        client, admin_token, "EXPIRED001", campaign["id"],
        expires_at=past,
    )
    user_id = _get_user_id(client, user_token)

    resp = _validate(client, user_token, user_id, "order-005", 1000, ["EXPIRED001"])
    assert resp.status_code == 422
    data = resp.get_json()
    assert data["error"] == "validation_error"
    assert any(d.get("error") == "coupon_expired" for d in data.get("details", []))


def test_coupon_not_yet_active(client, admin_token, user_token):
    """Coupon whose campaign hasn't started yet returns 422."""
    campaign = _create_campaign(
        client, admin_token,
        name="Future Campaign",
        start_offset_days=5,  # starts 5 days from now
        end_offset_days=30,
    )
    coupon = _create_coupon(client, admin_token, "FUTURE001", campaign["id"])
    user_id = _get_user_id(client, user_token)

    resp = _validate(client, user_token, user_id, "order-006", 1000, ["FUTURE001"])
    assert resp.status_code == 422
    data = resp.get_json()
    assert data["error"] == "validation_error"
    assert any(d.get("error") == "campaign_not_started" for d in data.get("details", []))


def test_per_user_cap_exceeded(client, admin_token, user_token):
    """Per-user cap: after 1 redemption, second validation for same user/coupon fails."""
    campaign = _create_campaign(client, admin_token, name="Per User Cap Campaign")
    coupon = _create_coupon(
        client, admin_token, "PERCAP001", campaign["id"],
        per_user_cap=1,
    )
    user_id = _get_user_id(client, user_token)

    # Record one redemption
    redeem_resp = _redeem(client, user_token, user_id, "order-cap-001", ["PERCAP001"])
    assert redeem_resp.status_code == 201

    # Now try to validate again
    resp = _validate(client, user_token, user_id, "order-cap-002", 1000, ["PERCAP001"])
    assert resp.status_code == 422
    data = resp.get_json()
    assert data["error"] == "validation_error"
    assert any(d.get("error") == "per_user_cap_exceeded" for d in data.get("details", []))


def test_global_max_redemptions_exceeded(client, admin_token, user_token):
    """Global max_redemptions: after 1 redemption, next validation fails."""
    campaign = _create_campaign(
        client, admin_token,
        name="Max Redemptions Campaign",
        max_redemptions=1,
    )
    coupon = _create_coupon(client, admin_token, "MAXRED001", campaign["id"])
    user_id = _get_user_id(client, user_token)

    # Record one redemption
    redeem_resp = _redeem(client, user_token, user_id, "order-max-001", ["MAXRED001"])
    assert redeem_resp.status_code == 201

    # Now try to validate again
    resp = _validate(client, user_token, user_id, "order-max-002", 1000, ["MAXRED001"])
    assert resp.status_code == 422
    data = resp.get_json()
    assert data["error"] == "validation_error"
    assert any(d.get("error") == "max_redemptions_exceeded" for d in data.get("details", []))


def test_min_order_cents_not_met(client, admin_token, user_token):
    """Order total below min_order_cents returns 422."""
    campaign = _create_campaign(
        client, admin_token,
        name="Min Order Campaign",
        min_order_cents=500,
    )
    coupon = _create_coupon(client, admin_token, "MINORD001", campaign["id"])
    user_id = _get_user_id(client, user_token)

    # Order is only 300 cents, below the 500 minimum
    resp = _validate(client, user_token, user_id, "order-007", 300, ["MINORD001"])
    assert resp.status_code == 422
    data = resp.get_json()
    assert data["error"] == "validation_error"
    assert any(d.get("error") == "min_order_not_met" for d in data.get("details", []))


def test_redeem_success(client, admin_token, user_token):
    """Successful redemption returns 201 with redemption records."""
    campaign = _create_campaign(client, admin_token, name="Redeem Success Campaign")
    coupon = _create_coupon(client, admin_token, "REDEEM001", campaign["id"])
    user_id = _get_user_id(client, user_token)

    resp = _redeem(client, user_token, user_id, "order-redeem-001", ["REDEEM001"])
    assert resp.status_code == 201
    data = resp.get_json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["user_id"] == user_id
    assert data[0]["order_id"] == "order-redeem-001"


def test_redeem_duplicate(client, admin_token, user_token):
    """Duplicate redemption (same user, coupon, order) returns 409."""
    campaign = _create_campaign(client, admin_token, name="Redeem Dup Campaign")
    coupon = _create_coupon(client, admin_token, "REDEEMDUP01", campaign["id"])
    user_id = _get_user_id(client, user_token)

    # First redemption
    resp1 = _redeem(client, user_token, user_id, "order-dup-001", ["REDEEMDUP01"])
    assert resp1.status_code == 201

    # Duplicate redemption
    resp2 = _redeem(client, user_token, user_id, "order-dup-001", ["REDEEMDUP01"])
    assert resp2.status_code == 409


def test_redemption_count_incremented(client, admin_token, user_token):
    """Campaign.redemption_count is incremented after a successful redemption."""
    campaign = _create_campaign(client, admin_token, name="Count Increment Campaign")
    campaign_id = campaign["id"]
    coupon = _create_coupon(client, admin_token, "COUNTINC01", campaign_id)
    user_id = _get_user_id(client, user_token)

    # Check initial count
    resp = client.get(
        f"/marketing/campaigns/{campaign_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["redemption_count"] == 0

    # Redeem
    _redeem(client, user_token, user_id, "order-count-001", ["COUNTINC01"])

    # Check incremented count
    resp = client.get(
        f"/marketing/campaigns/{campaign_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["redemption_count"] == 1


def test_non_admin_cannot_create_campaign(client, user_token):
    """Non-admin user gets 403 when trying to create a campaign."""
    resp = client.post(
        "/marketing/campaigns",
        json=_campaign_payload(name="Unauthorized Campaign"),
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 403


def test_idor_validate_as_other_user(client, admin_token, user_token):
    """User A cannot validate incentives with another user's user_id (IDOR)."""
    campaign = _create_campaign(client, admin_token, name="IDOR Validate Campaign")
    coupon = _create_coupon(client, admin_token, "IDORVAL001", campaign["id"])

    # Get admin's user_id
    admin_id = _get_admin_id(client, admin_token)
    user_id = _get_user_id(client, user_token)

    # User sends request with admin's user_id
    assert user_id != admin_id  # Sanity check

    resp = _validate(client, user_token, admin_id, "order-idor-001", 1000, ["IDORVAL001"])
    assert resp.status_code == 403
    data = resp.get_json()
    assert data["error"] == "forbidden"


def test_idor_redeem_as_other_user(client, admin_token, user_token):
    """User A cannot redeem coupons using another user's user_id (IDOR)."""
    campaign = _create_campaign(client, admin_token, name="IDOR Redeem Campaign")
    coupon = _create_coupon(client, admin_token, "IDORRED001", campaign["id"])

    # Get admin's user_id
    admin_id = _get_admin_id(client, admin_token)
    user_id = _get_user_id(client, user_token)

    # User sends request with admin's user_id
    assert user_id != admin_id  # Sanity check

    resp = _redeem(client, user_token, admin_id, "order-idor-002", ["IDORRED001"])
    assert resp.status_code == 403
    data = resp.get_json()
    assert data["error"] == "forbidden"
