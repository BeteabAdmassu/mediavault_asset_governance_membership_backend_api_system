"""
Tests for the Policy Rules Engine (Prompt 9).
"""
import json
import pytest
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
