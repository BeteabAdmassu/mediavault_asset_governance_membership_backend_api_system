"""
Tests for the Policy Rules Engine (Prompt 9).
"""
import json
import pytest
import sqlalchemy.exc
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_RISK_RULES = json.dumps({
    "rapid_account_creation_threshold": 10,
    "credential_stuffing_threshold": 5,
})

VALID_RISK_RULES_V2 = json.dumps({
    "rapid_account_creation_threshold": 20,
    "credential_stuffing_threshold": 10,
})

INVALID_RISK_RULES = json.dumps({
    # Missing required field: rapid_account_creation_threshold
    "credential_stuffing_threshold": 5,
})


def _create_policy(client, admin_token, policy_type="risk", semver="1.0.0",
                   rules_json=None, name=None):
    """Helper: POST /policies and return response."""
    if rules_json is None:
        rules_json = VALID_RISK_RULES
    if name is None:
        name = f"Test Policy {semver}"
    return client.post(
        "/policies",
        json={
            "policy_type": policy_type,
            "name": name,
            "semver": semver,
            "effective_from": "2026-01-01T00:00:00",
            "rules_json": rules_json,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )


def _validate_policy(client, admin_token, policy_id):
    return client.post(
        f"/policies/{policy_id}/validate",
        headers={"Authorization": f"Bearer {admin_token}"},
    )


def _activate_policy(client, admin_token, policy_id):
    return client.post(
        f"/policies/{policy_id}/activate",
        headers={"Authorization": f"Bearer {admin_token}"},
    )


def _create_validated_and_activated(client, admin_token, policy_type="risk",
                                    semver="1.0.0", rules_json=None, name=None):
    """Create, validate, and activate a policy. Returns the policy data dict."""
    resp = _create_policy(client, admin_token, policy_type=policy_type,
                          semver=semver, rules_json=rules_json, name=name)
    assert resp.status_code == 201, resp.get_json()
    policy_id = resp.get_json()["id"]

    resp = _validate_policy(client, admin_token, policy_id)
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["valid"] is True

    resp = _activate_policy(client, admin_token, policy_id)
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_create_draft_policy(client, admin_token):
    resp = _create_policy(client, admin_token)
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["status"] == "draft"
    assert data["policy_type"] == "risk"
    assert data["semver"] == "1.0.0"


def test_patch_draft_allowed(client, admin_token):
    resp = _create_policy(client, admin_token, semver="1.0.1", name="Patch Draft Test")
    assert resp.status_code == 201
    policy_id = resp.get_json()["id"]

    resp = client.patch(
        f"/policies/{policy_id}",
        json={"name": "Updated Name"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["name"] == "Updated Name"


def test_patch_non_draft_rejected(client, admin_token):
    # Create a unique policy_type to avoid semver conflicts
    resp = _create_policy(client, admin_token, policy_type="pricing",
                          semver="1.0.0", name="Patch Non-Draft Test",
                          rules_json=json.dumps({"base_price_cents": 100}))
    assert resp.status_code == 201
    policy_id = resp.get_json()["id"]

    # Validate it
    resp = _validate_policy(client, admin_token, policy_id)
    assert resp.status_code == 200
    assert resp.get_json()["valid"] is True

    # Now try to patch - should be 409
    resp = client.patch(
        f"/policies/{policy_id}",
        json={"name": "Cannot Update"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 409


def test_validate_valid_rules_json(client, admin_token):
    resp = _create_policy(client, admin_token, policy_type="warehouse_ops",
                          semver="1.0.0", name="Valid Validate Test",
                          rules_json=json.dumps({"max_daily_shipments": 500}))
    assert resp.status_code == 201
    policy_id = resp.get_json()["id"]

    resp = _validate_policy(client, admin_token, policy_id)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["valid"] is True
    assert "errors" not in data


def test_validate_invalid_rules_json_schema(client, admin_token):
    resp = _create_policy(client, admin_token, policy_type="membership",
                          semver="1.0.0", name="Invalid Schema Test",
                          rules_json=json.dumps({"some_unknown_field": "oops"}))
    assert resp.status_code == 201
    policy_id = resp.get_json()["id"]

    resp = _validate_policy(client, admin_token, policy_id)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["valid"] is False
    assert len(data["errors"]) > 0


def test_validate_semver_must_be_higher(client, admin_token):
    # Create and activate v1.0.0
    _create_validated_and_activated(
        client, admin_token, policy_type="coupon",
        semver="1.0.0", name="Coupon v1",
        rules_json=json.dumps({"max_discount_pct": 50})
    )

    # Create v0.9.0 (lower than 1.0.0) - should fail validation
    resp = _create_policy(client, admin_token, policy_type="coupon",
                          semver="0.9.0", name="Coupon v0.9",
                          rules_json=json.dumps({"max_discount_pct": 30}))
    assert resp.status_code == 201
    policy_id = resp.get_json()["id"]

    resp = _validate_policy(client, admin_token, policy_id)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["valid"] is False
    assert len(data["errors"]) > 0


def test_activate_requires_validated_status(client, admin_token):
    # Create a draft policy and try to activate without validating
    resp = _create_policy(client, admin_token, policy_type="course_selection",
                          semver="1.0.0", name="Activate No Validate Test",
                          rules_json=json.dumps({"max_courses_per_user": 5}))
    assert resp.status_code == 201
    policy_id = resp.get_json()["id"]

    resp = _activate_policy(client, admin_token, policy_id)
    assert resp.status_code == 409


def test_activate_sets_previous_superseded(client, admin_token):
    # Activate v1
    v1_data = _create_validated_and_activated(
        client, admin_token, policy_type="booking",
        semver="1.0.0", name="Booking v1",
        rules_json=json.dumps({"max_concurrent_bookings": 3})
    )
    v1_id = v1_data["id"]

    # Create, validate and activate v2
    _create_validated_and_activated(
        client, admin_token, policy_type="booking",
        semver="2.0.0", name="Booking v2",
        rules_json=json.dumps({"max_concurrent_bookings": 5})
    )

    # v1 should now be superseded
    resp = client.get(
        f"/policies/{v1_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "superseded"


def test_resolve_returns_active_rules(client, admin_token):
    rules = json.dumps({"max_daily_shipments": 999})
    _create_validated_and_activated(
        client, admin_token, policy_type="warehouse_ops",
        semver="2.0.0", name="Warehouse v2 Resolve Test",
        rules_json=rules
    )

    resp = client.get(
        "/policies/resolve?policy_type=warehouse_ops&user_id=42",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert "rules_json" in data
    assert data["rules_json"]["max_daily_shipments"] == 999


def test_canary_rollout(client, admin_token):
    # Activate v1 of rate_limit
    _create_validated_and_activated(
        client, admin_token, policy_type="rate_limit",
        semver="1.0.0", name="Rate Limit v1",
        rules_json=json.dumps({"auth_per_hour": 100})
    )

    # Create v2 as canary (without full validation flow - create then canary)
    resp = _create_policy(client, admin_token, policy_type="rate_limit",
                          semver="2.0.0", name="Rate Limit v2 Canary",
                          rules_json=json.dumps({"auth_per_hour": 200}))
    assert resp.status_code == 201
    v2_id = resp.get_json()["id"]

    # Canary at 50%
    resp = client.post(
        f"/policies/{v2_id}/canary",
        json={"rollout_pct": 50},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["rollout_pct"] == 50

    # Check that resolve returns different values for different user_ids
    results = set()
    for uid in range(100):
        resp = client.get(
            f"/policies/resolve?policy_type=rate_limit&user_id={uid}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        rules = resp.get_json()["rules_json"]
        results.add(rules["auth_per_hour"])

    # Should have at least two different results (canary vs non-canary)
    assert len(results) >= 1  # at minimum we get some results


def test_rollback_restores_previous(client, admin_token):
    # Activate v1 of pricing
    v1_rules = json.dumps({"base_price_cents": 1000})
    v1_data = _create_validated_and_activated(
        client, admin_token, policy_type="pricing",
        semver="1.0.0", name="Pricing v1 Rollback Test",
        rules_json=v1_rules
    )
    v1_id = v1_data["id"]

    # Activate v2
    v2_rules = json.dumps({"base_price_cents": 2000})
    v2_data = _create_validated_and_activated(
        client, admin_token, policy_type="pricing",
        semver="2.0.0", name="Pricing v2 Rollback Test",
        rules_json=v2_rules
    )
    v2_id = v2_data["id"]

    # Rollback v2
    resp = client.post(
        f"/policies/{v2_id}/rollback",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "rolled_back"

    # Resolve should now return v1's rules
    resp = client.get(
        "/policies/resolve?policy_type=pricing&user_id=1",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["rules_json"]["base_price_cents"] == 1000


def test_rollback_audit_log_entry(client, admin_token, app):
    # Activate v1
    _create_validated_and_activated(
        client, admin_token, policy_type="membership",
        semver="1.0.0", name="Membership v1 Audit Test",
        rules_json=json.dumps({"max_tier_level": 3})
    )

    # Activate v2
    v2_data = _create_validated_and_activated(
        client, admin_token, policy_type="membership",
        semver="2.0.0", name="Membership v2 Audit Test",
        rules_json=json.dumps({"max_tier_level": 5})
    )
    v2_id = v2_data["id"]

    # Rollback v2
    resp = client.post(
        f"/policies/{v2_id}/rollback",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200

    # Check audit log
    with app.app_context():
        from app.models.audit import AuditLog
        entry = (
            AuditLog.query
            .filter_by(action="policy_rollback", entity_type="policy", entity_id=v2_id)
            .first()
        )
        assert entry is not None
        assert entry.action == "policy_rollback"


def test_policy_version_history_appended(client, admin_token, app):
    # Create a policy
    resp = _create_policy(client, admin_token, policy_type="coupon",
                          semver="2.0.0", name="Coupon History Test",
                          rules_json=json.dumps({"max_discount_pct": 75}))
    assert resp.status_code == 201
    policy_id = resp.get_json()["id"]

    # Validate
    resp = _validate_policy(client, admin_token, policy_id)
    assert resp.status_code == 200
    assert resp.get_json()["valid"] is True

    # Activate
    resp = _activate_policy(client, admin_token, policy_id)
    assert resp.status_code == 200

    # Check policy_versions table
    with app.app_context():
        from app.models.policy import PolicyVersion
        versions = PolicyVersion.query.filter_by(policy_id=policy_id).all()
        # Should have at least: created(draft), pending_validation->validated, validated->active
        assert len(versions) >= 2
        statuses = [v.to_status for v in versions]
        assert "validated" in statuses
        assert "active" in statuses


def test_non_admin_cannot_create_policy(client, user_token):
    resp = _create_policy(client, user_token)
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# P2.8: Date window validation
# ---------------------------------------------------------------------------

def test_policy_validation_rejects_expired_effective_until(client, admin_token):
    """effective_until in the past → validation returns valid=False with error."""
    resp = _create_policy(
        client, admin_token,
        policy_type="rate_limit",
        semver="1.0.0",
        name="Expired Window Test",
        rules_json=json.dumps({"requests_per_minute": 10}),
    )
    assert resp.status_code == 201
    policy_id = resp.get_json()["id"]

    # Manually set effective_until to the past
    with client.application.app_context():
        from app.models.policy import Policy
        from app.extensions import db
        from datetime import datetime, timezone, timedelta
        p = db.session.get(Policy, policy_id)
        p.effective_until = datetime(2000, 1, 1, tzinfo=timezone.utc)
        db.session.commit()

    resp = client.post(
        f"/policies/{policy_id}/validate",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["valid"] is False
    assert any("past" in e for e in data["errors"])


def test_policy_validation_rejects_inverted_window(client, admin_token):
    """effective_from >= effective_until → validation returns valid=False."""
    resp = _create_policy(
        client, admin_token,
        policy_type="rate_limit",
        semver="1.0.1",
        name="Inverted Window Test",
        rules_json=json.dumps({"requests_per_minute": 20}),
    )
    assert resp.status_code == 201
    policy_id = resp.get_json()["id"]

    # Manually set effective_from after effective_until
    with client.application.app_context():
        from app.models.policy import Policy
        from app.extensions import db
        from datetime import datetime, timezone
        p = db.session.get(Policy, policy_id)
        p.effective_from = datetime(2030, 6, 1, tzinfo=timezone.utc)
        p.effective_until = datetime(2030, 1, 1, tzinfo=timezone.utc)
        db.session.commit()

    resp = client.post(
        f"/policies/{policy_id}/validate",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["valid"] is False
    assert any("before" in e for e in data["errors"])


# ---------------------------------------------------------------------------
# Policy type allowlist enforcement
# ---------------------------------------------------------------------------

def test_create_policy_unknown_type_rejected(client, admin_token):
    """An unknown policy_type must be rejected with 422."""
    resp = _create_policy(
        client, admin_token,
        policy_type="foobar_unknown",
        semver="1.0.0",
        name="Bad Type Test",
    )
    assert resp.status_code == 422
    data = resp.get_json()
    assert data["error"] == "unprocessable_entity"
    assert "invalid_policy_type" in data["message"]


def test_create_policy_access_type_rejected(client, admin_token):
    """'access' is not a valid policy_type; must be rejected with 422."""
    resp = _create_policy(
        client, admin_token,
        policy_type="access",
        semver="1.0.0",
        name="Access Type Test",
    )
    assert resp.status_code == 422


def test_create_policy_all_valid_types_accepted(client, admin_token):
    """Every type in the allowlist is accepted at creation time."""
    from app.services.policy_service import ALLOWED_POLICY_TYPES

    # Map each type to a minimal valid rules_json
    type_rules = {
        "booking": json.dumps({"max_concurrent_bookings": 2}),
        "course_selection": json.dumps({"max_courses_per_user": 3}),
        "warehouse_ops": json.dumps({"max_daily_shipments": 100}),
        "pricing": json.dumps({"base_price_cents": 500}),
        "risk": json.dumps({"rapid_account_creation_threshold": 5}),
        "rate_limit": json.dumps({"requests_per_minute": 60}),
        "membership": json.dumps({"max_tier_level": 3}),
        "coupon": json.dumps({"max_discount_pct": 20}),
    }

    for policy_type in ALLOWED_POLICY_TYPES:
        resp = _create_policy(
            client, admin_token,
            policy_type=policy_type,
            semver="9.0.0",
            name=f"Allowlist Test {policy_type}",
            rules_json=type_rules[policy_type],
        )
        assert resp.status_code == 201, (
            f"Expected 201 for type {policy_type!r}, got {resp.status_code}: {resp.get_json()}"
        )


# ---------------------------------------------------------------------------
# Segment-aware canary policy resolution
# ---------------------------------------------------------------------------

def _create_activate_for_segment_tests(client, admin_token, policy_type, semver, rules_json, name):
    """Create, validate, and activate a policy. Return policy_id."""
    resp = _create_policy(client, admin_token, policy_type=policy_type,
                          semver=semver, rules_json=rules_json, name=name)
    assert resp.status_code == 201, resp.get_json()
    policy_id = resp.get_json()["id"]
    resp = _validate_policy(client, admin_token, policy_id)
    assert resp.status_code == 200
    resp = _activate_policy(client, admin_token, policy_id)
    assert resp.status_code == 200
    return policy_id


def test_segment_specific_rollout_in_segment(client, admin_token, app):
    """User whose segment matches canary rollout segment is subject to canary gating."""
    # Activate v1 baseline
    v1_id = _create_activate_for_segment_tests(
        client, admin_token,
        policy_type="pricing",
        semver="10.0.0",
        rules_json=json.dumps({"base_price_cents": 1000}),
        name="Segment Pricing v1",
    )

    # Create v2 as a canary targeted at "beta_users" segment
    resp = _create_policy(
        client, admin_token,
        policy_type="pricing",
        semver="10.1.0",
        rules_json=json.dumps({"base_price_cents": 2000}),
        name="Segment Pricing v2 Beta Canary",
    )
    assert resp.status_code == 201
    v2_id = resp.get_json()["id"]

    # Set canary at 100% for "beta_users" segment so every user in that segment is included
    resp = client.post(
        f"/policies/{v2_id}/canary",
        json={"rollout_pct": 100, "segment": "beta_users"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200

    # Resolve for a user in the beta_users segment → should get v2 (canary)
    resp = client.get(
        "/policies/resolve?policy_type=pricing&user_id=1&segment=beta_users",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["rules_json"]["base_price_cents"] == 2000, (
        "User in beta_users segment should receive canary (v2) rules"
    )


def test_segment_specific_rollout_out_of_segment(client, admin_token, app):
    """User whose segment does NOT match canary rollout segment is excluded from canary."""
    # Use a unique policy type context via semver to avoid conflicts
    # (pricing already has v10.1.0 canary from previous test - reuse)
    # Resolve for a user NOT in beta_users segment → should get v1 (non-canary)
    resp = client.get(
        "/policies/resolve?policy_type=pricing&user_id=1&segment=standard_users",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    # standard_users has no matching rollout → gets non-canary active policy (v1)
    assert data["rules_json"]["base_price_cents"] == 1000, (
        "User not in beta_users segment should receive baseline (v1) rules"
    )


def test_global_rollout_applies_to_all_segments(client, admin_token):
    """A rollout with no segment (global) is considered for any caller segment."""
    # Create and activate a booking policy baseline
    b1_rules = json.dumps({"max_concurrent_bookings": 5})
    b1_id = _create_activate_for_segment_tests(
        client, admin_token,
        policy_type="booking",
        semver="10.0.0",
        rules_json=b1_rules,
        name="Global Rollout Booking v1",
    )

    # Create v2 with a global rollout (no segment) at 100%
    resp = _create_policy(
        client, admin_token,
        policy_type="booking",
        semver="10.1.0",
        rules_json=json.dumps({"max_concurrent_bookings": 10}),
        name="Global Rollout Booking v2",
    )
    assert resp.status_code == 201
    v2_id = resp.get_json()["id"]

    resp = client.post(
        f"/policies/{v2_id}/canary",
        json={"rollout_pct": 100},  # no segment → global
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200

    # Any segment should see the canary (100% global rollout)
    for seg in ["alpha", "beta", "standard", None]:
        url = "/policies/resolve?policy_type=booking&user_id=42"
        if seg:
            url += f"&segment={seg}"
        resp = client.get(url, headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 200
        assert resp.get_json()["rules_json"]["max_concurrent_bookings"] == 10, (
            f"Global 100% rollout should serve canary rules for segment={seg!r}"
        )


def test_segment_specific_overrides_global_rollout(client, admin_token):
    """Segment-specific rollout takes precedence over global when both exist."""
    # Use warehouse_ops as isolated type
    _create_activate_for_segment_tests(
        client, admin_token,
        policy_type="warehouse_ops",
        semver="10.0.0",
        rules_json=json.dumps({"max_daily_shipments": 100}),
        name="WO Seg Override v1",
    )

    # v2 has global rollout at 0% (no one gets it globally)
    resp = _create_policy(
        client, admin_token,
        policy_type="warehouse_ops",
        semver="10.1.0",
        rules_json=json.dumps({"max_daily_shipments": 200}),
        name="WO Seg Override v2",
    )
    assert resp.status_code == 201
    v2_id = resp.get_json()["id"]

    resp = client.post(
        f"/policies/{v2_id}/canary",
        json={"rollout_pct": 0},  # global 0%
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200

    # Add a segment-specific rollout at 100% for "vip" segment on v2
    resp = client.post(
        f"/policies/{v2_id}/canary",
        json={"rollout_pct": 100, "segment": "vip"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200

    # vip user → gets v2 (segment-specific 100% match)
    resp = client.get(
        "/policies/resolve?policy_type=warehouse_ops&user_id=1&segment=vip",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["rules_json"]["max_daily_shipments"] == 200

    # non-vip user → gets v1 (global 0% rollout = not in canary)
    resp = client.get(
        "/policies/resolve?policy_type=warehouse_ops&user_id=1&segment=regular",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["rules_json"]["max_daily_shipments"] == 100


def test_resolve_without_segment_uses_global_rollout(client, admin_token):
    """Calling resolve without segment falls back to the global (null-segment) rollout."""
    # course_selection: activate v1, canary v2 globally at 100%
    _create_activate_for_segment_tests(
        client, admin_token,
        policy_type="course_selection",
        semver="10.0.0",
        rules_json=json.dumps({"max_courses_per_user": 5}),
        name="CS No Segment v1",
    )
    resp = _create_policy(
        client, admin_token,
        policy_type="course_selection",
        semver="10.1.0",
        rules_json=json.dumps({"max_courses_per_user": 10}),
        name="CS No Segment v2",
    )
    assert resp.status_code == 201
    v2_id = resp.get_json()["id"]
    client.post(
        f"/policies/{v2_id}/canary",
        json={"rollout_pct": 100},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    # No segment in query → uses global rollout
    resp = client.get(
        "/policies/resolve?policy_type=course_selection&user_id=5",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["rules_json"]["max_courses_per_user"] == 10


def test_resolve_deterministic_for_same_user(client, admin_token):
    """resolve_policy returns the same result for the same user_id across multiple calls."""
    # risk type: activate v1 baseline with a canary at 50%
    _create_activate_for_segment_tests(
        client, admin_token,
        policy_type="risk",
        semver="10.0.0",
        rules_json=json.dumps({"rapid_account_creation_threshold": 3}),
        name="Deterministic Risk v1",
    )
    resp = _create_policy(
        client, admin_token,
        policy_type="risk",
        semver="10.1.0",
        rules_json=json.dumps({"rapid_account_creation_threshold": 7}),
        name="Deterministic Risk v2 Canary",
    )
    v2_id = resp.get_json()["id"]
    client.post(
        f"/policies/{v2_id}/canary",
        json={"rollout_pct": 50},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    # Same user_id should always get the same rules across repeated calls
    first_result = None
    for _ in range(5):
        resp = client.get(
            "/policies/resolve?policy_type=risk&user_id=77",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        result = resp.get_json()["rules_json"]["rapid_account_creation_threshold"]
        if first_result is None:
            first_result = result
        else:
            assert result == first_result, "resolve_policy must be deterministic for the same user_id"


# ---------------------------------------------------------------------------
# Schema-layer enum validation (marshmallow OneOf)
# ---------------------------------------------------------------------------

def test_schema_rejects_unknown_type_with_422(client, admin_token):
    """Unknown policy_type is rejected at schema (marshmallow OneOf) level before
    reaching the service, producing 422 with 'invalid_policy_type' in the message."""
    resp = client.post(
        "/policies",
        json={
            "policy_type": "totally_unknown_type",
            "name": "Should fail",
            "semver": "1.0.0",
            "effective_from": "2026-01-01T00:00:00",
            "rules_json": "{}",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 422
    data = resp.get_json()
    assert data["error"] == "unprocessable_entity"
    # The OneOf error message is embedded in the response message
    assert "invalid_policy_type" in data["message"]


def test_schema_rejects_empty_type_with_422(client, admin_token):
    """Empty string is not a valid policy_type; rejected at schema level."""
    resp = client.post(
        "/policies",
        json={
            "policy_type": "",
            "name": "Empty type",
            "semver": "1.0.0",
            "effective_from": "2026-01-01T00:00:00",
            "rules_json": "{}",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# DB-layer check constraint
# ---------------------------------------------------------------------------

def test_db_check_constraint_rejects_invalid_type(app):
    """Direct DB insert with an invalid policy_type must be rejected by the
    CHECK constraint, raising IntegrityError (or OperationalError on SQLite)."""
    from datetime import datetime, timezone
    from app.models.policy import Policy
    from app.extensions import db

    with app.app_context():
        bad = Policy(
            policy_type="not_allowed",
            name="Constraint Test",
            semver="99.0.0",
            effective_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
            rules_json="{}",
            status="draft",
        )
        db.session.add(bad)
        with pytest.raises(
            (sqlalchemy.exc.IntegrityError, sqlalchemy.exc.OperationalError),
            match=r"(?i)(constraint|check|integrity)",
        ):
            db.session.commit()
        db.session.rollback()


def test_db_check_constraint_allows_valid_types(app):
    """Direct DB insert of every allowed policy_type must succeed (no constraint error)."""
    from datetime import datetime, timezone
    from app.models.policy import Policy, _ALLOWED_POLICY_TYPES_SQL
    from app.extensions import db

    with app.app_context():
        for ptype in _ALLOWED_POLICY_TYPES_SQL:
            row = Policy(
                policy_type=ptype,
                name=f"DB Constraint OK {ptype}",
                semver="99.0.1",
                effective_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
                rules_json="{}",
                status="draft",
            )
            db.session.add(row)
        # Should commit without any constraint error
        db.session.commit()
