"""
Tests for Compliance: Data Export & Deletion (Prompt 11).
"""
import json
import pytest
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _create_export_request(client, token):
    resp = client.post("/compliance/export-request", headers=_auth(token))
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()


def _process_export(client, admin_token, request_id):
    resp = client.post(
        f"/compliance/export-request/{request_id}/process",
        headers=_auth(admin_token),
    )
    return resp


def _create_deletion_request(client, token):
    resp = client.post("/compliance/deletion-request", headers=_auth(token))
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()


def _process_deletion(client, admin_token, request_id):
    resp = client.post(
        f"/compliance/deletion-request/{request_id}/process",
        headers=_auth(admin_token),
    )
    return resp


def _get_user_id(client, token):
    resp = client.get("/auth/me", headers=_auth(token))
    return resp.get_json()["user_id"]


# ---------------------------------------------------------------------------
# Export tests
# ---------------------------------------------------------------------------

def test_export_request_created(client, user_token):
    """POST /compliance/export-request → 201 with request_id and status=pending."""
    data = _create_export_request(client, user_token)
    assert "request_id" in data
    assert data["status"] == "pending"


def test_export_download_before_process(client, user_token, app):
    """Download before processing → 404."""
    data = _create_export_request(client, user_token)
    request_id = data["request_id"]

    resp = client.get(
        f"/compliance/export-request/{request_id}/download",
        headers=_auth(user_token),
    )
    assert resp.status_code == 404


def test_export_process_generates_file(client, admin_token, user_token, app):
    """Processing an export request creates a file on disk."""
    import os

    data = _create_export_request(client, user_token)
    request_id = data["request_id"]

    resp = _process_export(client, admin_token, request_id)
    assert resp.status_code == 200, resp.get_data(as_text=True)

    # Check file exists
    with app.app_context():
        from app.services.compliance_service import get_export_file_path
        path = get_export_file_path(request_id)
    assert path is not None
    assert os.path.exists(path)


def test_export_file_is_valid_json(client, admin_token, user_token, app):
    """Export file contains valid JSON with expected keys."""
    data = _create_export_request(client, user_token)
    request_id = data["request_id"]

    resp = _process_export(client, admin_token, request_id)
    assert resp.status_code == 200

    with app.app_context():
        from app.services.compliance_service import get_export_file_path
        path = get_export_file_path(request_id)

    with open(path, 'r', encoding='utf-8') as f:
        export_data = json.load(f)

    assert "user" in export_data
    assert "profile" in export_data
    assert "ledger_entries" in export_data
    assert "assets" in export_data
    assert "audit_log" in export_data
    assert "coupon_redemptions" in export_data
    assert export_data["request_id"] == request_id


def test_export_download_by_owner(client, admin_token, user_token, app):
    """Owner can download their own export."""
    data = _create_export_request(client, user_token)
    request_id = data["request_id"]

    _process_export(client, admin_token, request_id)

    resp = client.get(
        f"/compliance/export-request/{request_id}/download",
        headers=_auth(user_token),
    )
    assert resp.status_code == 200
    assert resp.content_type == "application/json"


def test_export_download_by_other_user(client, admin_token, user_token, app):
    """Another non-admin user cannot download someone else's export → 403."""
    data = _create_export_request(client, user_token)
    request_id = data["request_id"]

    _process_export(client, admin_token, request_id)

    # Register a second user and get token
    resp = client.post(
        "/auth/register",
        json={
            "username": "other_export_user",
            "email": "other_export@example.com",
            "password": "OtherPass123!",
        },
    )
    assert resp.status_code == 201
    resp2 = client.post(
        "/auth/login",
        json={"username": "other_export_user", "password": "OtherPass123!"},
    )
    other_token = resp2.get_json()["token"]

    resp3 = client.get(
        f"/compliance/export-request/{request_id}/download",
        headers=_auth(other_token),
    )
    assert resp3.status_code == 403


# ---------------------------------------------------------------------------
# Deletion tests
# ---------------------------------------------------------------------------

def test_deletion_request_created(client, user_token):
    """POST /compliance/deletion-request → 201 with request_id and status=pending."""
    data = _create_deletion_request(client, user_token)
    assert "request_id" in data
    assert data["status"] == "pending"


def test_deletion_anonymizes_pii(client, admin_token, user_token, app):
    """After deletion, user PII is overwritten."""
    user_id = _get_user_id(client, user_token)

    data = _create_deletion_request(client, user_token)
    request_id = data["request_id"]

    resp = _process_deletion(client, admin_token, request_id)
    assert resp.status_code == 200

    with app.app_context():
        from app.models.auth import User
        user = User.query.get(user_id)
        assert user is not None
        assert user.username == f"deleted_{user_id}"
        assert user.email == f"deleted_{user_id}@redacted.local"
        assert user.phone_encrypted is None
        assert user.address_encrypted is None
        assert user.dob_encrypted is None
        assert user.status == "anonymized"


def test_deletion_clears_profile(client, admin_token, user_token, app):
    """After deletion, profile PII fields are cleared."""
    user_id = _get_user_id(client, user_token)

    data = _create_deletion_request(client, user_token)
    request_id = data["request_id"]

    resp = _process_deletion(client, admin_token, request_id)
    assert resp.status_code == 200

    with app.app_context():
        from app.models.profile import Profile
        profile = Profile.query.filter_by(user_id=user_id).first()
        if profile:
            assert profile.bio is None
            assert profile.interest_tags_json is None
            assert profile.media_references_json is None
            assert profile.display_name is None


def test_anonymized_account_cannot_login(client, admin_token, user_token, app):
    """Attempting to login with an anonymized account returns 401."""
    # Get username before deletion
    with app.app_context():
        from app.models.auth import User
        from app.services.auth_service import get_current_user
        from app.models.auth import Session
        # Get token and find user
        token_str = user_token
        session = Session.query.filter_by(token=token_str).first()
        user_id = session.user_id
        user = User.query.get(user_id)
        original_username = user.username

    data = _create_deletion_request(client, user_token)
    request_id = data["request_id"]

    resp = _process_deletion(client, admin_token, request_id)
    assert resp.status_code == 200

    # Try to login with the (now-deleted) username
    # The username is now deleted_<id>, so login attempt should fail
    resp2 = client.post(
        "/auth/login",
        json={"username": original_username, "password": "FixturePass123!"},
    )
    # Username no longer exists → unauthorized
    assert resp2.status_code == 401


def test_ledger_retained_after_deletion(client, admin_token, user_token, app):
    """Ledger entries are reassigned to sentinel user, not deleted."""
    user_id = _get_user_id(client, user_token)

    # Create a ledger entry for the user
    with app.app_context():
        from app.services.membership_service import credit_ledger
        import uuid
        credit_ledger(
            user_id=user_id,
            amount=100,
            currency="points",
            reason="test credit",
            idempotency_key=str(uuid.uuid4()),
        )

    data = _create_deletion_request(client, user_token)
    request_id = data["request_id"]

    resp = _process_deletion(client, admin_token, request_id)
    assert resp.status_code == 200

    with app.app_context():
        from app.models.membership import Ledger
        from app.services.compliance_service import get_or_create_sentinel_user
        sentinel = get_or_create_sentinel_user()

        # Ledger entries should have been reassigned to sentinel
        sentinel_entries = Ledger.query.filter_by(user_id=sentinel.id).all()
        assert len(sentinel_entries) > 0

        # No entries should remain for the original user
        user_entries = Ledger.query.filter_by(user_id=user_id).all()
        assert len(user_entries) == 0


def test_coupon_redemptions_retained(client, admin_token, user_token, app):
    """Coupon redemptions are left untouched after deletion."""
    user_id = _get_user_id(client, user_token)

    # Create a coupon redemption for the user
    with app.app_context():
        from app.models.marketing import Campaign, Coupon, CouponRedemption
        from app.extensions import db
        from datetime import datetime, timezone, timedelta

        campaign = Campaign(
            name="Test Campaign",
            type="discount",
            start_at=datetime.now(timezone.utc) - timedelta(days=1),
            end_at=datetime.now(timezone.utc) + timedelta(days=1),
            benefit_type="percent_off",
            benefit_value=10,
        )
        db.session.add(campaign)
        db.session.flush()

        coupon = Coupon(
            code=f"TEST-COUPON-{user_id}",
            campaign_id=campaign.id,
        )
        db.session.add(coupon)
        db.session.flush()

        redemption = CouponRedemption(
            user_id=user_id,
            coupon_id=coupon.id,
            order_id=f"order-{user_id}",
        )
        db.session.add(redemption)
        db.session.commit()

    data = _create_deletion_request(client, user_token)
    request_id = data["request_id"]

    resp = _process_deletion(client, admin_token, request_id)
    assert resp.status_code == 200

    with app.app_context():
        from app.models.marketing import CouponRedemption
        redemptions = CouponRedemption.query.filter_by(user_id=user_id).all()
        # Coupon redemptions are left untouched (still reference original user_id)
        assert len(redemptions) > 0


def test_deletion_appends_master_record(client, admin_token, user_token, app):
    """Deletion appends a master record history entry with to_status='anonymized'."""
    user_id = _get_user_id(client, user_token)

    data = _create_deletion_request(client, user_token)
    request_id = data["request_id"]

    resp = _process_deletion(client, admin_token, request_id)
    assert resp.status_code == 200

    with app.app_context():
        from app.models.audit import MasterRecord, MasterRecordHistory

        master = MasterRecord.query.filter_by(entity_type="user", entity_id=user_id).first()
        assert master is not None
        assert master.current_status == "anonymized"

        history = MasterRecordHistory.query.filter_by(
            master_record_id=master.id,
            to_status="anonymized",
        ).first()
        assert history is not None


def test_deletion_is_transactional(client, admin_token, user_token, app):
    """If any deletion step fails, changes are rolled back."""
    user_id = _get_user_id(client, user_token)

    data = _create_deletion_request(client, user_token)
    request_id = data["request_id"]

    # Monkeypatch transition_master_record to raise an error mid-transaction
    with patch(
        "app.services.compliance_service.transition_master_record",
        side_effect=RuntimeError("simulated failure"),
    ):
        resp = _process_deletion(client, admin_token, request_id)
        # Should fail (500 or similar)
        assert resp.status_code >= 400

    # User should still exist and NOT be anonymized
    with app.app_context():
        from app.models.auth import User
        user = User.query.get(user_id)
        assert user is not None
        assert user.status != "anonymized"
        assert "deleted_" not in user.username


def test_export_after_deletion_returns_anonymized_data(client, admin_token, user_token, app):
    """Export after deletion shows anonymized data."""
    user_id = _get_user_id(client, user_token)

    # First create and process a deletion
    del_data = _create_deletion_request(client, user_token)
    del_request_id = del_data["request_id"]
    _process_deletion(client, admin_token, del_request_id)

    # Now create an export request (admin creates it directly since user is anonymized)
    with app.app_context():
        from app.services.compliance_service import create_export_request, process_export
        exp_result = create_export_request(user_id=user_id)
        request_id = exp_result["request_id"]

        admin_id = None
        from app.models.auth import Session
        # Get admin user id from token
        admin_session = Session.query.filter_by(token=admin_token).first()
        if admin_session:
            admin_id = admin_session.user_id

        process_export(request_id=request_id, processed_by=admin_id)

        from app.services.compliance_service import get_export_file_path
        path = get_export_file_path(request_id)

    with open(path, 'r', encoding='utf-8') as f:
        export_data = json.load(f)

    # The user data should show the anonymized username/email
    assert export_data["user"]["username"] == f"deleted_{user_id}"
    assert export_data["user"]["email"] == f"deleted_{user_id}@redacted.local"
    assert export_data["user"]["status"] == "anonymized"


def test_idor_export_request_other_user(client, admin_token, user_token, app):
    """Non-admin cannot download another user's export → 403 not 404."""
    data = _create_export_request(client, user_token)
    request_id = data["request_id"]

    # Process the export
    _process_export(client, admin_token, request_id)

    # Create another user
    resp = client.post(
        "/auth/register",
        json={
            "username": "idor_test_user",
            "email": "idor_test@example.com",
            "password": "IdorTestPass123!",
        },
    )
    assert resp.status_code == 201
    resp2 = client.post(
        "/auth/login",
        json={"username": "idor_test_user", "password": "IdorTestPass123!"},
    )
    other_token = resp2.get_json()["token"]

    # This user tries to access another user's export
    resp3 = client.get(
        f"/compliance/export-request/{request_id}/download",
        headers=_auth(other_token),
    )
    # Must be 403, NOT 404 (to prevent information disclosure)
    assert resp3.status_code == 403


def test_idor_deletion_request_other_user(client, admin_token, user_token, app):
    """
    POST /compliance/deletion-request always creates a request for the
    authenticated user's own account. No way to create a deletion request
    for another user via this endpoint.
    """
    # user_token user creates a deletion request
    data = _create_deletion_request(client, user_token)
    user_id = _get_user_id(client, user_token)

    with app.app_context():
        from app.models.compliance import DataRequest
        req = DataRequest.query.get(data["request_id"])
        # The request must be for the authenticated user, not anyone else
        assert req.user_id == user_id

    # Create another user and verify they cannot trick the system
    resp = client.post(
        "/auth/register",
        json={
            "username": "idor_del_user",
            "email": "idor_del@example.com",
            "password": "IdorDelPass123!",
        },
    )
    assert resp.status_code == 201
    resp2 = client.post(
        "/auth/login",
        json={"username": "idor_del_user", "password": "IdorDelPass123!"},
    )
    other_token = resp2.get_json()["token"]
    other_user_id = _get_user_id(client, other_token)

    # Other user creates their own deletion request
    data2 = _create_deletion_request(client, other_token)

    with app.app_context():
        from app.models.compliance import DataRequest
        req2 = DataRequest.query.get(data2["request_id"])
        # Must be for the other user, not user_token's user
        assert req2.user_id == other_user_id
        assert req2.user_id != user_id


# ---------------------------------------------------------------------------
# P2.6: Sanitized error responses
# ---------------------------------------------------------------------------

def test_deletion_error_response_does_not_leak_internals(client, admin_token, user_token, app):
    """A simulated internal error on deletion returns a generic message, not a stack trace."""
    data = _create_deletion_request(client, user_token)
    request_id = data["request_id"]

    with patch(
        "app.services.compliance_service.transition_master_record",
        side_effect=RuntimeError("DB connection lost: secret-host:5432"),
    ):
        resp = _process_deletion(client, admin_token, request_id)
        assert resp.status_code == 500
        body = resp.get_json()
        # The raw exception message must NOT appear in the response body
        assert "DB connection lost" not in (body.get("message") or "")
        assert "secret-host" not in str(body)
        # A generic user-facing message must be present
        assert body.get("message") is not None
        assert len(body["message"]) > 0


# ---------------------------------------------------------------------------
# P2.7: Explicit 7-year retention policy
# ---------------------------------------------------------------------------

def test_ledger_retention_constant_is_seven_years():
    """LEDGER_RETENTION_YEARS must be 7 — any code change is a breaking compliance change."""
    from app.services.compliance_service import LEDGER_RETENTION_YEARS
    assert LEDGER_RETENTION_YEARS == 7


def test_is_within_retention_window_recent_record():
    """A record created today is within the 7-year retention window."""
    from app.services.compliance_service import is_within_retention_window
    from datetime import datetime, timezone
    assert is_within_retention_window(datetime.now(timezone.utc)) is True


def test_is_within_retention_window_old_record():
    """A record created 8 years ago is outside the retention window."""
    from app.services.compliance_service import is_within_retention_window
    from datetime import datetime, timezone, timedelta
    old_date = datetime.now(timezone.utc) - timedelta(days=365 * 8)
    assert is_within_retention_window(old_date) is False


def test_ledger_entries_retained_after_deletion(client, admin_token, user_token, app):
    """After deletion, ledger entries still exist (reassigned to sentinel)."""
    user_id = _get_user_id(client, user_token)

    with app.app_context():
        from app.services.membership_service import credit_ledger
        import uuid
        credit_ledger(
            user_id=user_id,
            amount=500,
            currency="points",
            reason="retention test",
            idempotency_key=f"retention-{uuid.uuid4()}",
        )

    data = _create_deletion_request(client, user_token)
    _process_deletion(client, admin_token, data["request_id"])

    with app.app_context():
        from app.models.membership import Ledger
        from app.services.compliance_service import get_or_create_sentinel_user
        sentinel = get_or_create_sentinel_user()
        # Ledger records must exist, just re-owned by sentinel
        retained = Ledger.query.filter_by(user_id=sentinel.id).all()
        assert len(retained) > 0, "Ledger entries were deleted instead of retained"


def test_deletion_classifies_entries_by_retention_window(client, admin_token, app):
    """
    Deletion flow classifies ledger entries by retention window and retains both.

    - Entries within 7-year window: legally mandated to retain.
    - Entries beyond 7-year window: retained anyway (policy: never hard-delete).
    Both categories are reassigned to sentinel; the audit log records counts.
    """
    from app.services.auth_service import register_user, login_user

    with app.app_context():
        try:
            register_user(
                "retention_cls_user",
                "retention_cls@test.com",
                "RetentionClsPass123!",
            )
        except ValueError:
            pass
        sess = login_user("retention_cls_user", "RetentionClsPass123!", ip="127.0.0.1")
        token = sess.token
        from app.models.auth import User
        u = User.query.filter_by(username="retention_cls_user").first()
        user_id = u.id

        # Insert one recent and one old ledger entry directly (bypassing service
        # helpers that would set created_at=now).
        from app.extensions import db
        from app.models.membership import Ledger
        from datetime import datetime, timezone, timedelta
        import uuid

        recent_entry = Ledger(
            user_id=user_id,
            amount=100,
            currency="points",
            entry_type="credit",
            reason="recent_cls_test",
            idempotency_key=f"cls-recent-{uuid.uuid4()}",
            created_at=datetime.now(timezone.utc) - timedelta(days=30),
        )
        old_entry = Ledger(
            user_id=user_id,
            amount=50,
            currency="points",
            entry_type="credit",
            reason="old_cls_test",
            idempotency_key=f"cls-old-{uuid.uuid4()}",
            # 8 years ago — outside the 7-year mandatory window
            created_at=datetime.now(timezone.utc) - timedelta(days=365 * 8),
        )
        db.session.add(recent_entry)
        db.session.add(old_entry)
        db.session.commit()
        recent_id = recent_entry.id
        old_id = old_entry.id

    # Process deletion
    data = _create_deletion_request(client, token)
    resp = _process_deletion(client, admin_token, data["request_id"])
    assert resp.status_code == 200

    with app.app_context():
        from app.extensions import db
        from app.models.membership import Ledger
        from app.services.compliance_service import get_or_create_sentinel_user, is_within_retention_window
        from datetime import datetime, timezone, timedelta

        sentinel = get_or_create_sentinel_user()

        # Both entries must survive (never hard-deleted)
        recent = db.session.get(Ledger, recent_id)
        old = db.session.get(Ledger, old_id)
        assert recent is not None, "Recent ledger entry was deleted — retention policy violated"
        assert old is not None, "Old ledger entry was deleted — retention policy violated"

        # Both must be re-owned by sentinel
        assert recent.user_id == sentinel.id, "Recent entry not reassigned to sentinel"
        assert old.user_id == sentinel.id, "Old entry not reassigned to sentinel"

        # Verify retention-window helper agrees on classification
        assert is_within_retention_window(recent.created_at) is True
        eight_years_ago = datetime.now(timezone.utc) - timedelta(days=365 * 8)
        assert is_within_retention_window(eight_years_ago) is False

        # Audit log should record the retention classification counts
        from app.models.audit import AuditLog
        import json
        audit = (
            AuditLog.query
            .filter_by(action="user_anonymized", entity_id=user_id)
            .order_by(AuditLog.created_at.desc())
            .first()
        )
        assert audit is not None
        detail = json.loads(audit.detail_json)
        # At least 1 entry in each bucket (recent + old)
        assert detail["ledger_within_retention_window"] >= 1
        assert detail["ledger_beyond_retention_window"] >= 1



def test_export_process_rate_limited(client, app, admin_token, user_token):
    """POST /compliance/export-request/<id>/process returns 429 after exceeding 30/minute."""
    from app.extensions import limiter

    # Create an export request to use as the target
    req_resp = client.post(
        "/compliance/export-request",
        headers=_auth(user_token),
    )
    assert req_resp.status_code == 201
    request_id = req_resp.get_json()["request_id"]

    with app.app_context():
        try:
            limiter.reset()
        except Exception:
            pass

    last_status = None
    for _ in range(31):
        r = client.post(
            f"/compliance/export-request/{request_id}/process",
            headers=_auth(admin_token),
        )
        last_status = r.status_code
        if last_status == 429:
            break
    assert last_status == 429, (
        "Expected 429 after exhausting 30/minute limit on POST /compliance/export-request/<id>/process"
    )


def test_deletion_process_rate_limited(client, app, admin_token, user_token):
    """POST /compliance/deletion-request/<id>/process returns 429 after exceeding 30/minute."""
    from app.extensions import limiter

    # Create a deletion request to use as the target
    req_resp = client.post(
        "/compliance/deletion-request",
        headers=_auth(user_token),
    )
    assert req_resp.status_code == 201
    request_id = req_resp.get_json()["request_id"]

    with app.app_context():
        try:
            limiter.reset()
        except Exception:
            pass

    last_status = None
    for _ in range(31):
        r = client.post(
            f"/compliance/deletion-request/{request_id}/process",
            headers=_auth(admin_token),
        )
        last_status = r.status_code
        if last_status == 429:
            break
    assert last_status == 429, (
        "Expected 429 after exhausting 30/minute limit on POST /compliance/deletion-request/<id>/process"
    )
