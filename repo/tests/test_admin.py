"""
Tests for Prompt 10: Master Records, Audit Trail & Admin Governance.
"""
import json
import os
import pytest

from tests.conftest import _create_user_direct, _make_admin


# ---------------------------------------------------------------------------
# 1. User creation creates a MasterRecord
# ---------------------------------------------------------------------------

def test_user_creation_creates_master_record(client, app):
    """Register a user; master_records should have entity_type='user' row."""
    resp = client.post(
        "/auth/register",
        json={
            "username": "mr_test_user",
            "email": "mr_test_user@example.com",
            "password": "TestPass123!",
        },
    )
    assert resp.status_code in (200, 201)

    with app.app_context():
        from app.models.auth import User
        from app.models.audit import MasterRecord
        user = User.query.filter_by(username="mr_test_user").first()
        assert user is not None
        record = MasterRecord.query.filter_by(entity_type="user", entity_id=user.id).first()
        assert record is not None
        assert record.current_status == "active"


# ---------------------------------------------------------------------------
# 2. Master record history appended on transition
# ---------------------------------------------------------------------------

def test_master_record_history_appended_on_transition(client, admin_token, app):
    """Admin POST /admin/master-records/user/{id}/transition appends a history row."""
    # Ensure there's a user with a master record
    with app.app_context():
        from app.models.auth import User
        from app.models.audit import MasterRecord, MasterRecordHistory

        user = User.query.filter_by(username="fixtureadmin").first()
        assert user is not None
        record = MasterRecord.query.filter_by(entity_type="user", entity_id=user.id).first()
        assert record is not None
        history_count_before = MasterRecordHistory.query.filter_by(
            master_record_id=record.id
        ).count()
        user_id = user.id

    resp = client.post(
        f"/admin/master-records/user/{user_id}/transition",
        json={"to_status": "suspended", "reason": "test suspension"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200

    with app.app_context():
        from app.models.audit import MasterRecord, MasterRecordHistory
        record = MasterRecord.query.filter_by(entity_type="user", entity_id=user_id).first()
        history_count_after = MasterRecordHistory.query.filter_by(
            master_record_id=record.id
        ).count()
        assert history_count_after > history_count_before
        assert record.current_status == "suspended"


# ---------------------------------------------------------------------------
# 3. History rows are immutable
# ---------------------------------------------------------------------------

def test_history_rows_are_immutable(client, admin_token, app):
    """Attempting to UPDATE a MasterRecordHistory row via SQLAlchemy raises RuntimeError."""
    with app.app_context():
        from app.models.audit import MasterRecordHistory
        from app.extensions import db

        history = MasterRecordHistory.query.first()
        assert history is not None, "No history rows found — run other tests first or seed data"

        with pytest.raises(RuntimeError):
            history.reason = "changed"
            db.session.flush()

        db.session.rollback()


# ---------------------------------------------------------------------------
# 4. snapshot_json contains entity state
# ---------------------------------------------------------------------------

def test_snapshot_json_contains_entity_state(client, admin_token, app):
    """History row's snapshot_json should contain entity fields."""
    with app.app_context():
        from app.models.auth import User
        from app.models.audit import MasterRecord
        user = User.query.filter_by(username="fixtureadmin").first()
        user_id = user.id

    resp = client.post(
        f"/admin/master-records/user/{user_id}/transition",
        json={"to_status": "active", "reason": "restore for snapshot test"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200

    with app.app_context():
        from app.models.audit import MasterRecord, MasterRecordHistory
        record = MasterRecord.query.filter_by(entity_type="user", entity_id=user_id).first()
        latest_history = (
            MasterRecordHistory.query
            .filter_by(master_record_id=record.id)
            .order_by(MasterRecordHistory.changed_at.desc())
            .first()
        )
        assert latest_history is not None
        assert latest_history.snapshot_json is not None
        snapshot = json.loads(latest_history.snapshot_json)
        assert "id" in snapshot or "username" in snapshot or "entity_type" in snapshot


# ---------------------------------------------------------------------------
# 5. Audit log on admin action
# ---------------------------------------------------------------------------

def test_audit_log_on_admin_action(client, admin_token, app):
    """Any admin API call should create an audit_logs row."""
    with app.app_context():
        from app.models.audit import AuditLog
        before_count = AuditLog.query.count()

    resp = client.get(
        "/admin/users",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200

    with app.app_context():
        from app.models.audit import AuditLog
        after_count = AuditLog.query.count()
        assert after_count > before_count


# ---------------------------------------------------------------------------
# 6. Audit log on login
# ---------------------------------------------------------------------------

def test_audit_log_on_login(client, app):
    """Successful login should produce an audit log with action='login_success'."""
    # Ensure user exists
    _create_user_direct(
        app,
        username="audit_login_user",
        email="audit_login_user@example.com",
        password="AuditPass123!",
    )

    with app.app_context():
        from app.models.audit import AuditLog
        from app.models.auth import User
        user = User.query.filter_by(username="audit_login_user").first()
        user_id = user.id
        before_count = AuditLog.query.filter_by(
            actor_id=user_id, action="login_success"
        ).count()

    client.post(
        "/auth/login",
        json={"username": "audit_login_user", "password": "AuditPass123!"},
    )

    with app.app_context():
        from app.models.audit import AuditLog
        after_count = AuditLog.query.filter_by(
            actor_id=user_id, action="login_success"
        ).count()
        assert after_count > before_count


# ---------------------------------------------------------------------------
# 7. Audit log on lockout
# ---------------------------------------------------------------------------

def test_audit_log_on_lockout(client, app):
    """Account lockout triggers an audit log with action='account_locked'."""
    # Create a fresh user for this test
    _create_user_direct(
        app,
        username="lockout_audit_user",
        email="lockout_audit_user@example.com",
        password="LockoutPass123!",
    )

    with app.app_context():
        from app.models.auth import User
        user = User.query.filter_by(username="lockout_audit_user").first()
        user_id = user.id

    # Trigger 5 failed login attempts to cause lockout
    for _ in range(5):
        client.post(
            "/auth/login",
            json={"username": "lockout_audit_user", "password": "WrongPassword!"},
        )

    with app.app_context():
        from app.models.audit import AuditLog
        locked_log = AuditLog.query.filter_by(
            actor_id=user_id, action="account_locked"
        ).first()
        assert locked_log is not None


# ---------------------------------------------------------------------------
# 8. Sensitive fields masked by default
# ---------------------------------------------------------------------------

def test_sensitive_fields_masked_by_default(client, admin_token, app):
    """GET /admin/users/{id} without purpose header returns masked sensitive fields."""
    # Create a user and set encrypted fields
    with app.app_context():
        from app.models.auth import User
        from app.services.encryption_service import encrypt_field
        from app.extensions import db

        # Register via service to get full user
        try:
            from app.services.auth_service import register_user
            register_user(
                username="masked_user_test",
                email="masked_user_test@example.com",
                password="MaskedPass123!",
            )
        except ValueError:
            pass

        user = User.query.filter_by(username="masked_user_test").first()
        user.phone_encrypted = encrypt_field("+1-555-867-5309")
        user.address_encrypted = encrypt_field("123 Test St, Springfield")
        user.dob_encrypted = encrypt_field("1990-01-01")
        db.session.commit()
        user_id = user.id

    resp = client.get(
        f"/admin/users/{user_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["phone"] == "***-***-XXXX"
    assert data["address"] == "[REDACTED]"
    assert data["dob"] == "[REDACTED]"


# ---------------------------------------------------------------------------
# 9. Sensitive fields unmasked with purpose header
# ---------------------------------------------------------------------------

def test_sensitive_fields_unmasked_with_purpose_header(client, admin_token, app):
    """Admin + X-Data-Access-Purpose header returns actual decrypted values."""
    with app.app_context():
        from app.models.auth import User
        from app.services.encryption_service import encrypt_field
        from app.extensions import db

        try:
            from app.services.auth_service import register_user
            register_user(
                username="unmasked_user_test",
                email="unmasked_user_test@example.com",
                password="UnmaskedPass123!",
            )
        except ValueError:
            pass

        user = User.query.filter_by(username="unmasked_user_test").first()
        user.phone_encrypted = encrypt_field("+1-555-123-4567")
        user.address_encrypted = encrypt_field("456 Main St, Testville")
        user.dob_encrypted = encrypt_field("1985-06-15")
        db.session.commit()
        user_id = user.id

    resp = client.get(
        f"/admin/users/{user_id}",
        headers={
            "Authorization": f"Bearer {admin_token}",
            "X-Data-Access-Purpose": "audit",
        },
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["phone"] == "+1-555-123-4567"
    assert data["address"] == "456 Main St, Testville"
    assert data["dob"] == "1985-06-15"


# ---------------------------------------------------------------------------
# 10. Purpose header recorded in audit log
# ---------------------------------------------------------------------------

def test_purpose_header_recorded_in_audit_log(client, admin_token, app):
    """Unmasked access logs the purpose value in audit log's detail_json."""
    with app.app_context():
        from app.models.auth import User
        from app.services.encryption_service import encrypt_field
        from app.extensions import db

        try:
            from app.services.auth_service import register_user
            register_user(
                username="purpose_log_user",
                email="purpose_log_user@example.com",
                password="PurposePass123!",
            )
        except ValueError:
            pass

        user = User.query.filter_by(username="purpose_log_user").first()
        user.phone_encrypted = encrypt_field("+1-555-999-0000")
        db.session.commit()
        user_id = user.id
        from app.models.audit import AuditLog
        before_count = AuditLog.query.filter_by(
            action="admin_view_user_unmasked", entity_id=user_id
        ).count()

    purpose_value = "fraud_investigation"
    resp = client.get(
        f"/admin/users/{user_id}",
        headers={
            "Authorization": f"Bearer {admin_token}",
            "X-Data-Access-Purpose": purpose_value,
        },
    )
    assert resp.status_code == 200

    with app.app_context():
        from app.models.audit import AuditLog
        log_entry = (
            AuditLog.query
            .filter_by(action="admin_view_user_unmasked", entity_id=user_id)
            .order_by(AuditLog.created_at.desc())
            .first()
        )
        assert log_entry is not None
        detail = json.loads(log_entry.detail_json)
        assert detail.get("purpose") == purpose_value


# ---------------------------------------------------------------------------
# 11. Non-admin cannot access admin users endpoint
# ---------------------------------------------------------------------------

def test_non_admin_cannot_access_admin_users(client, user_token):
    """GET /admin/users with a regular user token should return 403."""
    resp = client.get(
        "/admin/users",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 12. Get master record history chain
# ---------------------------------------------------------------------------

def test_get_master_record_history_chain(client, admin_token, app):
    """GET /admin/master-records/user/{id} returns an ordered history array."""
    with app.app_context():
        from app.models.auth import User
        user = User.query.filter_by(username="fixtureadmin").first()
        user_id = user.id

    resp = client.get(
        f"/admin/master-records/user/{user_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert "history" in data
    assert isinstance(data["history"], list)
    assert len(data["history"]) >= 1
    # Verify ordering: each entry's changed_at should be <= the next
    history = data["history"]
    for i in range(len(history) - 1):
        assert history[i]["changed_at"] <= history[i + 1]["changed_at"]


# ---------------------------------------------------------------------------
# 13. Audit log pagination
# ---------------------------------------------------------------------------

def test_audit_log_pagination(client, admin_token, app):
    """Seed 30 audit entries; GET /admin/audit-logs?page=2&per_page=10 returns 10 results."""
    with app.app_context():
        from app.services.audit_service import log_audit
        from app.extensions import db
        for i in range(30):
            log_audit(
                actor_id=None,
                actor_role="system",
                action=f"pagination_test_{i}",
                entity_type="test",
                entity_id=i,
                detail={"index": i},
                ip="127.0.0.1",
            )
        db.session.commit()

    resp = client.get(
        "/admin/audit-logs?page=2&per_page=10",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["items"]) == 10
    assert data["page"] == 2
    assert data["per_page"] == 10


# ---------------------------------------------------------------------------
# 14. Encryption key missing blocks startup
# ---------------------------------------------------------------------------

def test_encryption_key_missing_blocks_startup(app):
    """Unsetting FIELD_ENCRYPTION_KEY causes create_app() to raise RuntimeError."""
    env_key = os.environ.pop("FIELD_ENCRYPTION_KEY", None)
    try:
        with pytest.raises(RuntimeError, match="FIELD_ENCRYPTION_KEY"):
            from app import create_app
            create_app()
    finally:
        if env_key is not None:
            os.environ["FIELD_ENCRYPTION_KEY"] = env_key
