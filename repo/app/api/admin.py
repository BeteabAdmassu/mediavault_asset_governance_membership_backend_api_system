"""
Admin governance API blueprint.

Provides:
  GET  /admin/users                               – paginated user list
  GET  /admin/users/<id>                          – full profile (masked by default)
  PATCH /admin/users/<id>                         – update role / status
  GET  /admin/audit-logs                          – paginated, filterable
  GET  /admin/audit-logs/<id>                     – single entry
  GET  /admin/master-records/<entity_type>/<id>   – current record + history
  POST /admin/master-records/<entity_type>/<id>/transition – status transition
"""
import json

import flask_smorest
import marshmallow as ma
from flask import g, jsonify, request
from flask.views import MethodView

from app.utils.auth_utils import require_auth, require_role

blp = flask_smorest.Blueprint(
    "admin",
    "admin",
    url_prefix="/admin",
    description="Admin governance: users, audit logs, master records",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_user_roles(user):
    return [r.name for r in user.roles]


def _user_dict_masked(user):
    """User dict with sensitive fields masked."""
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "status": user.status,
        "locked_until": user.locked_until.isoformat() if user.locked_until else None,
        "roles": _get_user_roles(user),
        "phone": "***-***-XXXX",
        "address": "[REDACTED]",
        "dob": "[REDACTED]",
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "updated_at": user.updated_at.isoformat() if user.updated_at else None,
    }


def _user_dict_unmasked(user):
    """User dict with sensitive fields decrypted."""
    from app.services.encryption_service import decrypt_field
    phone = None
    address = None
    dob = None
    try:
        if user.phone_encrypted:
            phone = decrypt_field(user.phone_encrypted)
    except Exception:
        phone = None
    try:
        if user.address_encrypted:
            address = decrypt_field(user.address_encrypted)
    except Exception:
        address = None
    try:
        if user.dob_encrypted:
            dob = decrypt_field(user.dob_encrypted)
    except Exception:
        dob = None

    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "status": user.status,
        "locked_until": user.locked_until.isoformat() if user.locked_until else None,
        "roles": _get_user_roles(user),
        "phone": phone,
        "address": address,
        "dob": dob,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "updated_at": user.updated_at.isoformat() if user.updated_at else None,
    }


def _audit_log_dict(entry):
    detail = None
    if entry.detail_json:
        try:
            detail = json.loads(entry.detail_json)
        except Exception:
            detail = entry.detail_json
    return {
        "id": entry.id,
        "actor_id": entry.actor_id,
        "actor_role": entry.actor_role,
        "action": entry.action,
        "entity_type": entry.entity_type,
        "entity_id": entry.entity_id,
        "detail_json": detail,
        "ip": entry.ip,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
    }


def _history_dict(h):
    snapshot = None
    if h.snapshot_json:
        try:
            snapshot = json.loads(h.snapshot_json)
        except Exception:
            snapshot = h.snapshot_json
    return {
        "id": h.id,
        "master_record_id": h.master_record_id,
        "from_status": h.from_status,
        "to_status": h.to_status,
        "changed_by": h.changed_by,
        "changed_at": h.changed_at.isoformat() if h.changed_at else None,
        "snapshot_json": snapshot,
        "reason": h.reason,
    }


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

# Allowlist of platform role names that can be assigned via the admin API.
ALLOWED_ROLES = frozenset({"admin", "moderator", "reviewer", "user"})


class AdminUserPatchSchema(ma.Schema):
    role = ma.fields.Str(load_default=None)
    status = ma.fields.Str(load_default=None)


class MasterRecordTransitionSchema(ma.Schema):
    to_status = ma.fields.Str(required=True)
    reason = ma.fields.Str(required=True)


# ---------------------------------------------------------------------------
# /admin/users
# ---------------------------------------------------------------------------

@blp.route("/users")
class AdminUsersView(MethodView):
    @blp.doc(
        summary="List all users (Admin)",
        security=[{"BearerAuth": []}],
    )
    @require_auth
    @require_role("admin")
    def get(self):
        from app.models.auth import User
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 20, type=int)
        pagination = User.query.paginate(page=page, per_page=per_page, error_out=False)
        items = []
        for user in pagination.items:
            items.append({
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "status": user.status,
                "locked_until": user.locked_until.isoformat() if user.locked_until else None,
                "roles": _get_user_roles(user),
            })
        return jsonify({
            "items": items,
            "total": pagination.total,
            "page": pagination.page,
            "per_page": pagination.per_page,
            "pages": pagination.pages,
        }), 200


@blp.route("/users/<int:id>")
class AdminUserDetailView(MethodView):
    @blp.doc(
        summary="Get full user profile (Admin). Sensitive fields masked by default.",
        security=[{"BearerAuth": []}],
    )
    @require_auth
    @require_role("admin")
    def get(self, id):
        from app.models.auth import User
        from app.services.audit_service import log_audit
        from app.extensions import db

        user = db.session.get(User, id)
        if user is None:
            return jsonify({"error": "not_found", "message": f"User {id} not found"}), 404

        purpose = request.headers.get("X-Data-Access-Purpose", "").strip()
        actor = g.current_user
        actor_roles = {r.name for r in actor.roles}

        if purpose and "admin" in actor_roles:
            # Unmasked access – log the purpose
            data = _user_dict_unmasked(user)
            log_audit(
                actor_id=actor.id,
                actor_role="admin",
                action="admin_view_user_unmasked",
                entity_type="user",
                entity_id=id,
                detail={"purpose": purpose},
                ip=request.remote_addr,
            )
            db.session.commit()
        else:
            data = _user_dict_masked(user)

        return jsonify(data), 200

    @blp.doc(
        summary="Update user role or status (Admin)",
        security=[{"BearerAuth": []}],
    )
    @blp.arguments(AdminUserPatchSchema)
    @require_auth
    @require_role("admin")
    def patch(self, patch_data, id):
        from app.models.auth import User, Role, UserRole
        from app.services.audit_service import log_audit
        from app.extensions import db

        user = db.session.get(User, id)
        if user is None:
            return jsonify({"error": "not_found", "message": f"User {id} not found"}), 404

        actor = g.current_user
        changes = {}

        # Update status
        new_status = patch_data.get("status")
        if new_status is not None:
            old_status = user.status
            user.status = new_status
            changes["status"] = {"from": old_status, "to": new_status}

        # Update role
        new_role_name = patch_data.get("role")
        if new_role_name is not None:
            if new_role_name not in ALLOWED_ROLES:
                return jsonify({
                    "error": "unprocessable_entity",
                    "message": (
                        f"Invalid role '{new_role_name}'. "
                        f"Allowed roles: {sorted(ALLOWED_ROLES)}"
                    ),
                }), 422
            role = Role.query.filter_by(name=new_role_name).first()
            if role is None:
                role = Role(name=new_role_name)
                db.session.add(role)
                db.session.flush()
            existing = UserRole.query.filter_by(user_id=user.id, role_id=role.id).first()
            if not existing:
                db.session.add(UserRole(user_id=user.id, role_id=role.id))
            changes["role_added"] = new_role_name

        log_audit(
            actor_id=actor.id,
            actor_role="admin",
            action="admin_update_user",
            entity_type="user",
            entity_id=id,
            detail=changes,
            ip=request.remote_addr,
        )
        db.session.commit()

        return jsonify(_user_dict_masked(user)), 200


# ---------------------------------------------------------------------------
# /admin/audit-logs
# ---------------------------------------------------------------------------

@blp.route("/audit-logs")
class AdminAuditLogsView(MethodView):
    @blp.doc(
        summary="List audit logs, filterable (Admin)",
        security=[{"BearerAuth": []}],
    )
    @require_auth
    @require_role("admin")
    def get(self):
        from app.models.audit import AuditLog
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 20, type=int)
        actor_id = request.args.get("actor_id", type=int)
        entity_type = request.args.get("entity_type")
        action = request.args.get("action")
        date_from = request.args.get("date_from")
        date_to = request.args.get("date_to")

        query = AuditLog.query
        if actor_id is not None:
            query = query.filter(AuditLog.actor_id == actor_id)
        if entity_type:
            query = query.filter(AuditLog.entity_type == entity_type)
        if action:
            query = query.filter(AuditLog.action == action)
        if date_from:
            from datetime import datetime
            try:
                dt = datetime.fromisoformat(date_from)
                query = query.filter(AuditLog.created_at >= dt)
            except ValueError:
                pass
        if date_to:
            from datetime import datetime
            try:
                dt = datetime.fromisoformat(date_to)
                query = query.filter(AuditLog.created_at <= dt)
            except ValueError:
                pass

        query = query.order_by(AuditLog.created_at.desc())
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)

        return jsonify({
            "items": [_audit_log_dict(e) for e in pagination.items],
            "total": pagination.total,
            "page": pagination.page,
            "per_page": pagination.per_page,
            "pages": pagination.pages,
        }), 200


@blp.route("/audit-logs/<int:id>")
class AdminAuditLogDetailView(MethodView):
    @blp.doc(
        summary="Get single audit log entry (Admin)",
        security=[{"BearerAuth": []}],
    )
    @require_auth
    @require_role("admin")
    def get(self, id):
        from app.models.audit import AuditLog
        from app.extensions import db
        entry = db.session.get(AuditLog, id)
        if entry is None:
            return jsonify({"error": "not_found", "message": f"AuditLog {id} not found"}), 404
        return jsonify(_audit_log_dict(entry)), 200


# ---------------------------------------------------------------------------
# /admin/master-records
# ---------------------------------------------------------------------------

@blp.route("/master-records/<entity_type>/<int:entity_id>")
class AdminMasterRecordView(MethodView):
    @blp.doc(
        summary="Get master record with full history chain (Admin)",
        security=[{"BearerAuth": []}],
    )
    @require_auth
    @require_role("admin")
    def get(self, entity_type, entity_id):
        from app.models.audit import MasterRecord, MasterRecordHistory
        record = MasterRecord.query.filter_by(
            entity_type=entity_type,
            entity_id=entity_id,
        ).first()
        if record is None:
            return jsonify({"error": "not_found", "message": f"No MasterRecord for {entity_type}:{entity_id}"}), 404

        history = (
            MasterRecordHistory.query
            .filter_by(master_record_id=record.id)
            .order_by(MasterRecordHistory.changed_at.asc())
            .all()
        )

        return jsonify({
            "id": record.id,
            "entity_type": record.entity_type,
            "entity_id": record.entity_id,
            "current_status": record.current_status,
            "created_by": record.created_by,
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "updated_at": record.updated_at.isoformat() if record.updated_at else None,
            "history": [_history_dict(h) for h in history],
        }), 200


@blp.route("/master-records/<entity_type>/<int:entity_id>/transition")
class AdminMasterRecordTransitionView(MethodView):
    @blp.doc(
        summary="Transition master record status (Admin)",
        security=[{"BearerAuth": []}],
    )
    @blp.arguments(MasterRecordTransitionSchema)
    @require_auth
    @require_role("admin")
    def post(self, data, entity_type, entity_id):
        from app.services.master_record_service import transition_master_record
        from app.services.audit_service import log_audit
        from app.extensions import db

        actor = g.current_user
        to_status = data["to_status"]
        reason = data["reason"]

        # Build a snapshot of the entity
        snapshot = _get_entity_snapshot(entity_type, entity_id)

        try:
            record = transition_master_record(
                entity_type=entity_type,
                entity_id=entity_id,
                to_status=to_status,
                changed_by=actor.id,
                reason=reason,
                snapshot=snapshot,
            )
        except ValueError as exc:
            return jsonify({"error": "not_found", "message": str(exc)}), 404

        log_audit(
            actor_id=actor.id,
            actor_role="admin",
            action="master_record_transition",
            entity_type=entity_type,
            entity_id=entity_id,
            detail={"to_status": to_status, "reason": reason},
            ip=request.remote_addr,
        )
        db.session.commit()

        return jsonify({
            "id": record.id,
            "entity_type": record.entity_type,
            "entity_id": record.entity_id,
            "current_status": record.current_status,
        }), 200


def _get_entity_snapshot(entity_type, entity_id):
    """Build a snapshot dict for the given entity."""
    try:
        if entity_type == "user":
            from app.models.auth import User
            from app.extensions import db
            user = db.session.get(User, entity_id)
            if user:
                return {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                    "status": user.status,
                    "roles": [r.name for r in user.roles],
                }
        elif entity_type == "asset":
            from app.models.asset import Asset
            from app.extensions import db
            asset = db.session.get(Asset, entity_id)
            if asset:
                return {
                    "id": asset.id,
                    "title": asset.title,
                    "asset_type": asset.asset_type,
                    "status": getattr(asset, "status", None),
                }
        elif entity_type == "policy":
            from app.models.policy import Policy
            from app.extensions import db
            policy = db.session.get(Policy, entity_id)
            if policy:
                return {
                    "id": policy.id,
                    "name": policy.name,
                    "status": policy.status,
                    "semver": policy.semver,
                }
    except Exception:
        pass
    return {"entity_type": entity_type, "entity_id": entity_id}
