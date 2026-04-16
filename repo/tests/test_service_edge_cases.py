"""
Service-layer unit tests for edge cases and boundary conditions
that are hard to reach through the API alone.
"""
import json
import pytest
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Encryption service
# ---------------------------------------------------------------------------

def test_encrypt_decrypt_roundtrip(app):
    """encrypt_field → decrypt_field returns the original plaintext."""
    from app.services.encryption_service import encrypt_field, decrypt_field
    with app.app_context():
        original = "sensitive-data-123"
        encrypted = encrypt_field(original)
        assert encrypted != original
        assert isinstance(encrypted, str)
        decrypted = decrypt_field(encrypted)
        assert decrypted == original


def test_decrypt_invalid_ciphertext_raises(app):
    """decrypt_field with garbage base64 raises (invalid GCM tag)."""
    from app.services.encryption_service import decrypt_field
    with app.app_context():
        with pytest.raises(Exception):
            # Valid base64 but not valid AES-GCM ciphertext
            decrypt_field("bm90LXZhbGlkLWVuY3J5cHRlZA==")


def test_encrypt_none_returns_none(app):
    """encrypt_field(None) returns None."""
    from app.services.encryption_service import encrypt_field
    with app.app_context():
        assert encrypt_field(None) is None


def test_decrypt_none_returns_none(app):
    """decrypt_field(None) returns None."""
    from app.services.encryption_service import decrypt_field
    with app.app_context():
        assert decrypt_field(None) is None


def test_encrypt_empty_string_returns_none(app):
    """encrypt_field('') returns None (falsy guard)."""
    from app.services.encryption_service import encrypt_field
    with app.app_context():
        assert encrypt_field("") is None


def test_mask_functions_return_fixed_strings():
    """mask_phone, mask_address, mask_dob return stable redacted strings."""
    from app.services.encryption_service import mask_phone, mask_address, mask_dob
    assert mask_phone() == "***-***-XXXX"
    assert mask_address() == "[REDACTED]"
    assert mask_dob() == "[REDACTED]"


# ---------------------------------------------------------------------------
# Audit service
# ---------------------------------------------------------------------------

def test_audit_log_creation_persists_detail(app):
    """log_audit creates an AuditLog entry with correct detail_json."""
    from app.services.audit_service import log_audit
    from app.models.audit import AuditLog
    from app.extensions import db
    import json as _json

    with app.app_context():
        log_audit(
            actor_id=1, actor_role="admin", action="svc_test_action",
            entity_type="test", entity_id=42,
            detail={"key": "value"}, ip="127.0.0.1",
        )
        entry = AuditLog.query.filter_by(action="svc_test_action").first()
        assert entry is not None
        assert entry.actor_id == 1
        assert entry.entity_type == "test"
        assert entry.entity_id == 42
        detail = _json.loads(entry.detail_json)
        assert detail["key"] == "value"


# ---------------------------------------------------------------------------
# Risk service — threshold loading
# ---------------------------------------------------------------------------

def test_risk_thresholds_defaults_have_expected_shape(app):
    """_get_thresholds returns dict with expected signals, each a dict with count/window/severity."""
    from app.services.risk_service import _get_thresholds
    with app.app_context():
        thresholds = _get_thresholds()
        assert isinstance(thresholds, dict)
        expected_signals = [
            "rapid_account_creation", "credential_stuffing",
            "reserve_abandon", "coupon_cycling", "high_velocity_profile_edit",
        ]
        for signal in expected_signals:
            assert signal in thresholds
            cfg = thresholds[signal]
            assert isinstance(cfg, dict)
            assert "count" in cfg
            assert "window_minutes" in cfg
            assert "severity" in cfg
            assert isinstance(cfg["count"], int) and cfg["count"] >= 1


def test_risk_thresholds_from_policy_overrides_count(app):
    """Active risk policy overrides count while preserving window_minutes and severity."""
    from app.services.risk_service import _get_thresholds, THRESHOLDS
    from app.models.policy import Policy
    from app.extensions import db

    with app.app_context():
        # Park existing active risk policies
        existing = Policy.query.filter_by(policy_type="risk", status="active").all()
        old_statuses = [(p.id, p.status) for p in existing]
        for p in existing:
            p.status = "superseded"
        db.session.commit()

        p = Policy(
            policy_type="risk", name="Threshold Override Test",
            semver="99.0.0", status="active",
            effective_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
            rules_json=json.dumps({"rapid_account_creation_threshold": 42}),
        )
        db.session.add(p)
        db.session.commit()

        try:
            thresholds = _get_thresholds()
            rac = thresholds["rapid_account_creation"]
            assert rac["count"] == 42, f"expected count=42 from override, got {rac['count']}"
            # window and severity should match THRESHOLDS defaults
            assert rac["window_minutes"] == THRESHOLDS["rapid_account_creation"]["window_minutes"]
            assert rac["severity"] == THRESHOLDS["rapid_account_creation"]["severity"]
            # Signals without overrides keep their defaults
            assert thresholds["credential_stuffing"]["count"] == THRESHOLDS["credential_stuffing"]["count"]
        finally:
            p.status = "superseded"
            for pid, old_status in old_statuses:
                old_p = db.session.get(Policy, pid)
                if old_p:
                    old_p.status = old_status
            db.session.commit()


def test_risk_thresholds_bad_json_falls_back_to_defaults(app):
    """Invalid rules_json in active policy → falls back to all default counts."""
    from app.services.risk_service import _get_thresholds, THRESHOLDS
    from app.models.policy import Policy
    from app.extensions import db

    with app.app_context():
        existing = Policy.query.filter_by(policy_type="risk", status="active").all()
        old_statuses = [(p.id, p.status) for p in existing]
        for p in existing:
            p.status = "superseded"
        db.session.commit()

        p = Policy(
            policy_type="risk", name="Bad JSON Risk SVC",
            semver="99.1.0", status="active",
            effective_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
            rules_json="NOT VALID JSON",
        )
        db.session.add(p)
        db.session.commit()

        try:
            thresholds = _get_thresholds()
            # Should be identical to THRESHOLDS since JSON is unparseable
            assert thresholds == THRESHOLDS
        finally:
            p.status = "superseded"
            for pid, old_status in old_statuses:
                old_p = db.session.get(Policy, pid)
                if old_p:
                    old_p.status = old_status
            db.session.commit()


# ---------------------------------------------------------------------------
# Membership service — tier assignment
# ---------------------------------------------------------------------------

def test_membership_tier_assignment_uses_basic_tier(app):
    """New membership for an unknown user gets basic tier if it exists."""
    from app.services.membership_service import _get_or_create_membership
    from app.models.membership import MembershipTier
    from app.extensions import db

    with app.app_context():
        m = _get_or_create_membership(user_id=9999)
        db.session.commit()
        assert m is not None
        # If basic tier exists, it should be assigned
        basic = MembershipTier.query.filter_by(name="Basic").first()
        if basic:
            assert m.tier_id == basic.id


# ---------------------------------------------------------------------------
# Policy lifecycle via API
# ---------------------------------------------------------------------------

def test_create_policy_invalid_type_returns_422(client, admin_token):
    """POST /policies with unknown policy_type → 422 with error detail."""
    resp = client.post("/policies", json={
        "policy_type": "totally_invalid", "name": "Bad",
        "semver": "1.0.0", "effective_from": "2026-01-01T00:00:00",
        "rules_json": "{}",
    }, headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 422


def test_policy_lifecycle_create_validate_activate(client, admin_token):
    """Create → validate → activate a policy through its full lifecycle."""
    h = {"Authorization": f"Bearer {admin_token}"}
    cr = client.post("/policies", json={
        "policy_type": "warehouse_ops", "name": "Lifecycle Test",
        "semver": "99.9.0", "effective_from": "2026-01-01T00:00:00",
        "rules_json": json.dumps({"max_daily_shipments": 10}),
    }, headers=h)
    assert cr.status_code == 201
    pid = cr.get_json()["id"]
    assert cr.get_json()["status"] == "draft"

    rv = client.post(f"/policies/{pid}/validate", headers=h)
    assert rv.status_code == 200
    # validate_policy returns {"valid": True} on success
    assert rv.get_json()["valid"] is True

    ra = client.post(f"/policies/{pid}/activate", headers=h)
    assert ra.status_code == 200
    # activate returns the policy object
    assert ra.get_json()["id"] == pid


# ---------------------------------------------------------------------------
# Compliance service — failure modes
# ---------------------------------------------------------------------------

def test_export_nonexistent_raises_lookup_error(app):
    """process_export with nonexistent request_id raises LookupError."""
    from app.services.compliance_service import process_export
    with app.app_context():
        with pytest.raises(LookupError):
            process_export(request_id=999999, processed_by=1)


def test_deletion_nonexistent_raises_lookup_error(app):
    """process_deletion with nonexistent request_id raises LookupError."""
    from app.services.compliance_service import process_deletion
    with app.app_context():
        with pytest.raises(LookupError):
            process_deletion(request_id=999999, processed_by=1)


# ---------------------------------------------------------------------------
# Master record — correct path-based route
# ---------------------------------------------------------------------------

def test_master_record_get_nonexistent_returns_404(client, admin_token):
    """GET /admin/master-records/user/999999 → 404 with error envelope."""
    resp = client.get(
        "/admin/master-records/user/999999",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "not_found"
