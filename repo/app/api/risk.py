"""
Risk Control & Anomaly Detection API blueprint.
"""
import json
from datetime import datetime, timezone

import flask_smorest
import marshmallow as ma
from marshmallow import validate
from flask import request, g, jsonify
from flask.views import MethodView

from app.utils.auth_utils import require_auth, require_auth_allow_blacklisted, require_role, get_user_rate_key
from app.extensions import db, limiter

blp = flask_smorest.Blueprint(
    "risk",
    "risk",
    url_prefix="/risk",
    description="Risk Control & Anomaly Detection",
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class EvaluateRequestSchema(ma.Schema):
    event_type = ma.fields.Str(required=True)
    user_id = ma.fields.Int(load_default=None)
    ip = ma.fields.Str(load_default=None)
    device_id = ma.fields.Str(load_default=None)
    metadata = ma.fields.Dict(load_default=None)


class EvaluateResponseSchema(ma.Schema):
    decision = ma.fields.Str()
    reasons = ma.fields.List(ma.fields.Str())


class RiskEventSchema(ma.Schema):
    id = ma.fields.Int()
    event_type = ma.fields.Str()
    user_id = ma.fields.Int(allow_none=True)
    ip = ma.fields.Str(allow_none=True)
    device_id = ma.fields.Str(allow_none=True)
    decision = ma.fields.Str(allow_none=True)
    reasons = ma.fields.Raw(allow_none=True)
    metadata_json = ma.fields.Str(allow_none=True)
    created_at = ma.fields.Str()


class RiskEventsQuerySchema(ma.Schema):
    user_id = ma.fields.Int(load_default=None)
    ip = ma.fields.Str(load_default=None)
    event_type = ma.fields.Str(load_default=None)
    date_from = ma.fields.Str(load_default=None)
    date_to = ma.fields.Str(load_default=None)
    decision = ma.fields.Str(load_default=None)
    page = ma.fields.Int(load_default=1)
    per_page = ma.fields.Int(load_default=20)


class BlacklistCreateSchema(ma.Schema):
    target_type = ma.fields.Str(
        required=True,
        validate=validate.OneOf(["user", "device", "ip"]),
    )
    target_id = ma.fields.Str(required=True)
    reason = ma.fields.Str(required=True)
    start_at = ma.fields.Str(load_default=None)
    end_at = ma.fields.Str(load_default=None)


class BlacklistResponseSchema(ma.Schema):
    id = ma.fields.Int()
    target_type = ma.fields.Str()
    target_id = ma.fields.Str()
    reason = ma.fields.Str()
    start_at = ma.fields.Str(allow_none=True)
    end_at = ma.fields.Str(allow_none=True)
    appeal_status = ma.fields.Str()
    created_at = ma.fields.Str()


class AppealUpdateSchema(ma.Schema):
    appeal_status = ma.fields.Str(
        required=True,
        validate=validate.OneOf(["approved", "rejected"]),
    )


class MessageSchema(ma.Schema):
    message = ma.fields.Str()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize_blacklist(entry):
    return {
        "id": entry.id,
        "target_type": entry.target_type,
        "target_id": entry.target_id,
        "reason": entry.reason,
        "start_at": entry.start_at.isoformat() if entry.start_at else None,
        "end_at": entry.end_at.isoformat() if entry.end_at else None,
        "appeal_status": entry.appeal_status,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
    }


def _serialize_risk_event(event):
    reasons = event.reasons
    if reasons:
        try:
            reasons = json.loads(reasons)
        except (ValueError, TypeError):
            pass
    return {
        "id": event.id,
        "event_type": event.event_type,
        "user_id": event.user_id,
        "ip": event.ip,
        "device_id": event.device_id,
        "decision": event.decision,
        "reasons": reasons,
        "metadata_json": event.metadata_json,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


def _check_ip_blacklist(ip):
    """Return True if the given IP is actively blacklisted."""
    if not ip:
        return False
    now = datetime.now(timezone.utc)
    entry = (
        db.session.query(__import__("app.models.risk", fromlist=["Blacklist"]).Blacklist)
        .filter(
            __import__("app.models.risk", fromlist=["Blacklist"]).Blacklist.target_type == "ip",
            __import__("app.models.risk", fromlist=["Blacklist"]).Blacklist.target_id == ip,
            __import__("app.models.risk", fromlist=["Blacklist"]).Blacklist.start_at <= now,
            (
                __import__("app.models.risk", fromlist=["Blacklist"]).Blacklist.end_at == None  # noqa: E711
            ) | (
                __import__("app.models.risk", fromlist=["Blacklist"]).Blacklist.end_at > now
            ),
        )
        .first()
    )
    return entry is not None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@blp.route("/evaluate")
class EvaluateView(MethodView):
    @blp.doc(
        summary="Evaluate risk for an event",
        description="Submit an event for risk evaluation. Returns decision and triggered signals.",
        security=[{"BearerAuth": []}],
    )
    @blp.arguments(EvaluateRequestSchema)
    @blp.response(200, EvaluateResponseSchema)
    @require_auth
    @limiter.limit("60/minute", key_func=get_user_rate_key)
    def post(self, data):
        from app.services.risk_service import evaluate_risk

        ip = data.get("ip") or request.remote_addr or "unknown"

        # Check IP blacklist before evaluation
        from app.models.risk import Blacklist
        now = datetime.now(timezone.utc)
        ip_blacklisted = (
            Blacklist.query
            .filter(
                Blacklist.target_type == "ip",
                Blacklist.target_id == ip,
                Blacklist.start_at <= now,
                (Blacklist.end_at == None) | (Blacklist.end_at > now),  # noqa: E711
            )
            .first()
        )
        if ip_blacklisted:
            return jsonify({"error": "forbidden", "message": "IP address is blacklisted"}), 403

        # P1.5: Non-admin callers cannot specify an arbitrary user_id.
        # Force the evaluated user_id to the authenticated user; only admins
        # may submit on behalf of another user.
        caller = g.current_user
        is_admin = any(r.name == "admin" for r in caller.roles)
        if is_admin:
            eval_user_id = data.get("user_id")
        else:
            eval_user_id = caller.id

        result = evaluate_risk(
            event_type=data["event_type"],
            ip=ip,
            user_id=eval_user_id,
            device_id=data.get("device_id"),
            metadata=data.get("metadata"),
        )
        return result


@blp.route("/events")
class RiskEventsView(MethodView):
    @blp.doc(
        summary="List risk events (admin only)",
        description="Paginated, filterable list of risk events.",
        security=[{"BearerAuth": []}],
    )
    @blp.arguments(RiskEventsQuerySchema, location="query")
    @require_auth
    @require_role("admin")
    def get(self, query):
        from app.models.risk import RiskEvent

        q = db.session.query(RiskEvent)

        if query.get("user_id"):
            q = q.filter(RiskEvent.user_id == query["user_id"])
        if query.get("ip"):
            q = q.filter(RiskEvent.ip == query["ip"])
        if query.get("event_type"):
            q = q.filter(RiskEvent.event_type == query["event_type"])
        if query.get("decision"):
            q = q.filter(RiskEvent.decision == query["decision"])
        if query.get("date_from"):
            try:
                dt = datetime.fromisoformat(query["date_from"])
                q = q.filter(RiskEvent.created_at >= dt)
            except ValueError:
                pass
        if query.get("date_to"):
            try:
                dt = datetime.fromisoformat(query["date_to"])
                q = q.filter(RiskEvent.created_at <= dt)
            except ValueError:
                pass

        page = max(1, query.get("page", 1))
        per_page = min(100, max(1, query.get("per_page", 20)))
        total = q.count()
        events = q.order_by(RiskEvent.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()

        return jsonify({
            "total": total,
            "page": page,
            "per_page": per_page,
            "items": [_serialize_risk_event(e) for e in events],
        })


@blp.route("/blacklist")
class BlacklistView(MethodView):
    @blp.doc(
        summary="Create a blacklist entry (admin only)",
        description="Add a user, device, or IP to the blacklist.",
        security=[{"BearerAuth": []}],
    )
    @blp.arguments(BlacklistCreateSchema)
    @require_auth
    @limiter.limit("30/minute", key_func=get_user_rate_key)
    @require_role("admin")
    def post(self, data):
        from app.models.risk import Blacklist

        now = datetime.now(timezone.utc)

        start_at = now
        if data.get("start_at"):
            try:
                start_at = datetime.fromisoformat(data["start_at"])
            except ValueError:
                pass

        end_at = None
        if data.get("end_at"):
            try:
                end_at = datetime.fromisoformat(data["end_at"])
            except ValueError:
                pass

        entry = Blacklist(
            target_type=data["target_type"],
            target_id=str(data["target_id"]),
            reason=data["reason"],
            start_at=start_at,
            end_at=end_at,
            reviewer_id=g.current_user.id,
            appeal_status="none",
        )
        db.session.add(entry)
        db.session.flush()

        # Create MasterRecord for this blacklist entry
        from app.services.master_record_service import create_master_record
        create_master_record(
            entity_type="blacklist",
            entity_id=entry.id,
            initial_status="active",
            created_by=g.current_user.id,
        )

        db.session.commit()

        return jsonify(_serialize_blacklist(entry)), 201

    @blp.doc(
        summary="List active blacklist entries (admin only)",
        description="Returns blacklist entries that are currently active.",
        security=[{"BearerAuth": []}],
    )
    @require_auth
    @require_role("admin")
    def get(self):
        from app.models.risk import Blacklist

        now = datetime.now(timezone.utc)
        entries = (
            Blacklist.query
            .filter(
                Blacklist.start_at <= now,
                (Blacklist.end_at == None) | (Blacklist.end_at > now),  # noqa: E711
            )
            .order_by(Blacklist.created_at.desc())
            .all()
        )
        return jsonify([_serialize_blacklist(e) for e in entries])


@blp.route("/blacklist/<int:id>")
class BlacklistDetailView(MethodView):
    @blp.doc(
        summary="Soft-delete a blacklist entry (admin only)",
        description="Sets end_at to now, effectively expiring the blacklist entry.",
        security=[{"BearerAuth": []}],
    )
    @require_auth
    @limiter.limit("30/minute", key_func=get_user_rate_key)
    @require_role("admin")
    def delete(self, id):
        from app.models.risk import Blacklist

        entry = Blacklist.query.get(id)
        if not entry:
            return jsonify({"error": "not_found", "message": "Blacklist entry not found"}), 404

        entry.end_at = datetime.now(timezone.utc)
        db.session.commit()

        return jsonify({"message": "Blacklist entry expired", "id": id})


@blp.route("/blacklist/<int:id>/appeal")
class BlacklistAppealView(MethodView):
    @blp.doc(
        summary="Submit an appeal for a blacklist entry",
        description=(
            "Sets the appeal_status to 'pending'. "
            "For user-type entries: only the affected user or an admin/reviewer may appeal. "
            "For device/IP entries: only admin/reviewer may appeal. "
            "Blacklisted users may still call this endpoint."
        ),
        security=[{"BearerAuth": []}],
    )
    @require_auth_allow_blacklisted
    @limiter.limit("30/minute", key_func=get_user_rate_key)
    def post(self, id):
        from app.models.risk import Blacklist

        entry = Blacklist.query.get(id)
        if not entry:
            return jsonify({"error": "not_found", "message": "Blacklist entry not found"}), 404

        # P1.3: Object-level authorization on appeals.
        caller = g.current_user
        is_privileged = any(r.name in ("admin", "reviewer") for r in caller.roles)

        if not is_privileged:
            if entry.target_type == "user":
                if entry.target_id != str(caller.id):
                    return jsonify({
                        "error": "forbidden",
                        "message": "You may only appeal a blacklist entry that targets your own account.",
                    }), 403
            else:
                # device / IP blacklists can only be appealed by admins or reviewers
                return jsonify({
                    "error": "forbidden",
                    "message": "Only an admin or reviewer may appeal a device or IP blacklist entry.",
                }), 403

        entry.appeal_status = "pending"
        db.session.commit()

        return jsonify({"message": "Appeal submitted", "appeal_status": entry.appeal_status})

    @blp.doc(
        summary="Review an appeal (admin only)",
        description="Update appeal_status to 'approved' or 'rejected'.",
        security=[{"BearerAuth": []}],
    )
    @blp.arguments(AppealUpdateSchema)
    @require_auth
    @limiter.limit("30/minute", key_func=get_user_rate_key)
    @require_role("admin")
    def patch(self, data, id):
        from app.models.risk import Blacklist

        entry = Blacklist.query.get(id)
        if not entry:
            return jsonify({"error": "not_found", "message": "Blacklist entry not found"}), 404

        entry.appeal_status = data["appeal_status"]
        db.session.commit()

        return jsonify({"message": "Appeal updated", "appeal_status": entry.appeal_status})
