"""
Compliance service: data export and deletion (GDPR-style).
"""
import json
import os
import secrets
from datetime import datetime, timezone

from sqlalchemy import text

from app.extensions import db
from app.models.compliance import DataRequest
from app.services.master_record_service import transition_master_record
from app.services.audit_service import log_audit


# ---------------------------------------------------------------------------
# Exports directory
# ---------------------------------------------------------------------------

def _get_exports_dir():
    exports_dir = os.path.join(os.path.dirname(__file__), '..', 'data', 'exports')
    os.makedirs(exports_dir, exist_ok=True)
    return os.path.abspath(exports_dir)


# ---------------------------------------------------------------------------
# Sentinel user
# ---------------------------------------------------------------------------

def get_or_create_sentinel_user():
    """
    Get or create the sentinel 'deleted user' record.
    Looks up by username='deleted_user_sentinel'.
    """
    from app.models.auth import User
    sentinel = User.query.filter_by(username='deleted_user_sentinel').first()
    if sentinel is None:
        from passlib.context import CryptContext
        _pwd_context = CryptContext(schemes=["bcrypt"], bcrypt__rounds=4, deprecated="auto")
        random_pw = secrets.token_urlsafe(32)
        sentinel = User(
            username='deleted_user_sentinel',
            email='sentinel@redacted.local',
            password_hash=_pwd_context.hash(random_pw),
            status='anonymized',
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.session.add(sentinel)
        db.session.flush()
        # Create a master record for sentinel user so it doesn't break FK constraints
        try:
            from app.services.master_record_service import create_master_record
            create_master_record(
                entity_type="user",
                entity_id=sentinel.id,
                initial_status="anonymized",
                created_by=sentinel.id,
            )
        except Exception:
            pass  # If master record creation fails, continue
        db.session.commit()
    return sentinel


# ---------------------------------------------------------------------------
# Export request
# ---------------------------------------------------------------------------

def create_export_request(user_id):
    """Create DataRequest with type='export', status='pending'."""
    req = DataRequest(
        user_id=user_id,
        type='export',
        status='pending',
        requested_at=datetime.now(timezone.utc),
    )
    db.session.add(req)
    db.session.commit()
    return {"request_id": req.id, "status": req.status}


def process_export(request_id, processed_by):
    """
    Admin: collect all user data and serialize to JSON file.
    """
    from app.models.auth import User, Session
    from app.models.profile import Profile, VisibilityGroup, VisibilityGroupMember
    from app.models.membership import Membership, Ledger
    from app.models.asset import Asset
    from app.models.risk import RiskEvent
    from app.models.audit import AuditLog
    from app.models.marketing import CouponRedemption

    req = db.session.get(DataRequest, request_id)
    if req is None:
        raise LookupError("request_not_found")

    user_id = req.user_id
    user = db.session.get(User, user_id)
    if user is None:
        raise LookupError("user_not_found")

    # Collect all user data
    profile = Profile.query.filter_by(user_id=user_id).first()
    membership = Membership.query.filter_by(user_id=user_id).first()
    ledger_entries = Ledger.query.filter_by(user_id=user_id).all()
    assets = Asset.query.filter_by(created_by=user_id).all()
    risk_events = RiskEvent.query.filter_by(user_id=user_id).all()
    audit_logs = AuditLog.query.filter_by(actor_id=user_id).all()
    coupon_redemptions = CouponRedemption.query.filter_by(user_id=user_id).all()

    def _dt(v):
        return v.isoformat() if v else None

    export_data = {
        "export_generated_at": datetime.now(timezone.utc).isoformat(),
        "request_id": request_id,
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "status": user.status,
            "created_at": _dt(user.created_at),
            "updated_at": _dt(user.updated_at),
        },
        "profile": {
            "display_name": profile.display_name if profile else None,
            "bio": profile.bio if profile else None,
            "interest_tags_json": profile.interest_tags_json if profile else None,
            "media_references_json": profile.media_references_json if profile else None,
            "visibility_scope": profile.visibility_scope if profile else None,
        } if profile else None,
        "membership": {
            "tier_id": membership.tier_id if membership else None,
            "points_balance": membership.points_balance if membership else 0,
            "stored_value_balance": membership.stored_value_balance if membership else 0,
            "tier_since": _dt(membership.tier_since) if membership else None,
        } if membership else None,
        "ledger_entries": [
            {
                "id": e.id,
                "amount": e.amount,
                "currency": e.currency,
                "entry_type": e.entry_type,
                "reason": e.reason,
                "idempotency_key": e.idempotency_key,
                "reference_id": e.reference_id,
                "created_at": _dt(e.created_at),
            }
            for e in ledger_entries
        ],
        "assets": [
            {
                "id": a.id,
                "title": a.title,
                "asset_type": a.asset_type,
                "description": a.description,
                "created_at": _dt(a.created_at),
            }
            for a in assets
        ],
        "risk_events": [
            {
                "id": r.id,
                "event_type": r.event_type,
                "decision": r.decision,
                "created_at": _dt(r.created_at),
            }
            for r in risk_events
        ],
        "audit_log": [
            {
                "id": a.id,
                "action": a.action,
                "entity_type": a.entity_type,
                "entity_id": a.entity_id,
                "created_at": _dt(a.created_at),
            }
            for a in audit_logs
        ],
        "coupon_redemptions": [
            {
                "id": c.id,
                "coupon_id": c.coupon_id,
                "order_id": c.order_id,
                "redeemed_at": _dt(c.redeemed_at),
            }
            for c in coupon_redemptions
        ],
    }

    # Write to file
    exports_dir = _get_exports_dir()
    file_path = os.path.join(exports_dir, f"{request_id}.json")
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(export_data, f, indent=2, ensure_ascii=False)

    # Update request
    req.status = 'complete'
    req.completed_at = datetime.now(timezone.utc)
    db.session.commit()

    return {"request_id": request_id, "status": "complete", "file": file_path}


def get_export_file_path(request_id):
    """Return path to export file. Return None if not complete."""
    req = db.session.get(DataRequest, request_id)
    if req is None or req.status != 'complete':
        return None
    exports_dir = _get_exports_dir()
    file_path = os.path.join(exports_dir, f"{request_id}.json")
    if os.path.exists(file_path):
        return file_path
    return None


def get_export_file(request_id, requesting_user_id, is_admin):
    """
    Return export file path with access control.
    - If not admin and requesting_user_id != request.user_id → raise 403
    - If status != 'complete' → raise 404
    """
    req = db.session.get(DataRequest, request_id)
    if req is None:
        raise LookupError("not_found")

    # IDOR check: non-admin users can only access their own requests
    if not is_admin and req.user_id != requesting_user_id:
        raise PermissionError("forbidden")

    if req.status != 'complete':
        raise LookupError("not_found")

    exports_dir = _get_exports_dir()
    file_path = os.path.join(exports_dir, f"{request_id}.json")
    if not os.path.exists(file_path):
        raise LookupError("not_found")

    return file_path


# ---------------------------------------------------------------------------
# Deletion request
# ---------------------------------------------------------------------------

def create_deletion_request(user_id):
    """Create DataRequest with type='deletion', status='pending'."""
    req = DataRequest(
        user_id=user_id,
        type='deletion',
        status='pending',
        requested_at=datetime.now(timezone.utc),
    )
    db.session.add(req)
    db.session.commit()
    return {"request_id": req.id, "status": req.status}


def process_deletion(request_id, processed_by):
    """
    Admin: anonymize user in a single transaction.
    """
    from app.models.auth import User, Session
    from app.models.profile import Profile, VisibilityGroupMember

    req = db.session.get(DataRequest, request_id)
    if req is None:
        raise LookupError("request_not_found")

    user_id = req.user_id
    user = db.session.get(User, user_id)
    if user is None:
        raise LookupError("user_not_found")

    try:
        now = datetime.now(timezone.utc)

        # Step 1: Overwrite PII
        user.username = f'deleted_{user_id}'
        user.email = f'deleted_{user_id}@redacted.local'
        user.phone_encrypted = None
        user.address_encrypted = None
        user.dob_encrypted = None

        # Step 2: Clear profile
        profile = Profile.query.filter_by(user_id=user_id).first()
        if profile:
            profile.bio = None
            profile.interest_tags_json = None
            profile.media_references_json = None
            profile.display_name = None

        # Step 3: Delete visibility group memberships
        VisibilityGroupMember.query.filter_by(user_id=user_id).delete()

        # Step 4: Set user status to anonymized
        user.status = 'anonymized'
        user.anonymized_at = now

        # Step 5: Revoke all active sessions
        Session.query.filter_by(user_id=user_id).filter(
            Session.revoked_at == None  # noqa: E711
        ).update({"revoked_at": now})

        db.session.flush()

        # Step 6: Reassign ledger entries to sentinel user via raw SQL (bypasses immutability listener)
        sentinel = get_or_create_sentinel_user()
        db.session.execute(
            text("UPDATE ledgers SET user_id = :sentinel_id WHERE user_id = :user_id"),
            {"sentinel_id": sentinel.id, "user_id": user_id}
        )

        # Step 7: Leave coupon_redemptions untouched (per spec)

        # Step 8: Append master record history
        transition_master_record(
            entity_type="user",
            entity_id=user_id,
            to_status="anonymized",
            changed_by=processed_by,
            reason="User deletion request processed",
        )

        # Step 9: Write audit log entry
        log_audit(
            actor_id=processed_by,
            actor_role="admin",
            action="user_anonymized",
            entity_type="user",
            entity_id=user_id,
            detail={"request_id": request_id, "processed_by": processed_by},
            ip=None,
        )

        # Step 10: Update DataRequest status
        req.status = 'complete'
        req.completed_at = now

        db.session.commit()

    except Exception:
        db.session.rollback()
        raise

    return {"status": "anonymized"}


# ---------------------------------------------------------------------------
# Admin: list data requests
# ---------------------------------------------------------------------------

def get_data_requests(page=1, per_page=20, type=None, status=None):
    """Admin: list all data requests."""
    query = DataRequest.query

    if type is not None:
        query = query.filter(DataRequest.type == type)
    if status is not None:
        query = query.filter(DataRequest.status == status)

    query = query.order_by(DataRequest.requested_at.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return pagination
