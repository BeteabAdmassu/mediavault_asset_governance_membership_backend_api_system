"""
Policy Rules Engine API blueprint.
"""
import flask_smorest
import marshmallow as ma
from flask import g, jsonify, request
from flask.views import MethodView

from app.utils.auth_utils import require_auth, require_role

blp = flask_smorest.Blueprint(
    "policies",
    "policies",
    url_prefix="/policies",
    description="Policy Rules Engine - create, validate, activate, and resolve policies",
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class PolicyCreateSchema(ma.Schema):
    policy_type = ma.fields.Str(required=True)
    name = ma.fields.Str(required=True)
    semver = ma.fields.Str(required=True)
    effective_from = ma.fields.DateTime(required=True)
    rules_json = ma.fields.Str(required=True)
    effective_until = ma.fields.DateTime(allow_none=True, load_default=None)
    description = ma.fields.Str(allow_none=True, load_default=None)


class PolicyUpdateSchema(ma.Schema):
    name = ma.fields.Str()
    semver = ma.fields.Str()
    effective_from = ma.fields.DateTime()
    rules_json = ma.fields.Str()
    effective_until = ma.fields.DateTime(allow_none=True)
    description = ma.fields.Str(allow_none=True)


class CanarySchema(ma.Schema):
    rollout_pct = ma.fields.Int(required=True)
    segment = ma.fields.Str(allow_none=True, load_default=None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _policy_dict(policy):
    return {
        "id": policy.id,
        "policy_type": policy.policy_type,
        "name": policy.name,
        "semver": policy.semver,
        "effective_from": policy.effective_from.isoformat() if policy.effective_from else None,
        "effective_until": policy.effective_until.isoformat() if policy.effective_until else None,
        "rules_json": policy.rules_json,
        "description": policy.description,
        "status": policy.status,
        "created_by": policy.created_by,
        "created_at": policy.created_at.isoformat() if policy.created_at else None,
        "updated_at": policy.updated_at.isoformat() if policy.updated_at else None,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@blp.route("")
class PoliciesView(MethodView):
    @blp.doc(
        summary="Create a new policy in draft status (Admin)",
        security=[{"BearerAuth": []}],
    )
    @blp.arguments(PolicyCreateSchema)
    @require_auth
    @require_role("admin")
    def post(self, data):
        from app.services.policy_service import create_policy
        user = g.current_user
        policy = create_policy(
            policy_type=data["policy_type"],
            name=data["name"],
            semver=data["semver"],
            effective_from=data["effective_from"],
            rules_json=data["rules_json"],
            created_by=user.id,
            effective_until=data.get("effective_until"),
            description=data.get("description"),
        )
        return jsonify(_policy_dict(policy)), 201

    @blp.doc(
        summary="List all policies (Admin), optionally filtered by policy_type",
        security=[{"BearerAuth": []}],
    )
    @require_auth
    @require_role("admin")
    def get(self):
        from app.services.policy_service import get_policies
        policy_type = request.args.get("policy_type")
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 20, type=int)
        pagination = get_policies(policy_type=policy_type, page=page, per_page=per_page)
        return jsonify({
            "items": [_policy_dict(p) for p in pagination.items],
            "total": pagination.total,
            "page": pagination.page,
            "per_page": pagination.per_page,
            "pages": pagination.pages,
        }), 200


@blp.route("/resolve")
class PolicyResolveView(MethodView):
    @blp.doc(
        summary="Resolve effective policy rules for a user (Admin/internal)",
        security=[{"BearerAuth": []}],
    )
    @require_auth
    @require_role("admin")
    def get(self):
        from app.services.policy_service import resolve_policy
        policy_type = request.args.get("policy_type")
        user_id = request.args.get("user_id", type=int)
        if not policy_type or user_id is None:
            return jsonify({"error": "bad_request", "message": "policy_type and user_id are required"}), 400
        try:
            rules = resolve_policy(policy_type, user_id)
        except LookupError as exc:
            return jsonify({"error": "not_found", "message": str(exc)}), 404
        return jsonify({"rules_json": rules}), 200


@blp.route("/<int:id>")
class PolicyDetailView(MethodView):
    @blp.doc(
        summary="Get a single policy (Admin)",
        security=[{"BearerAuth": []}],
    )
    @require_auth
    @require_role("admin")
    def get(self, id):
        from app.services.policy_service import get_policy
        try:
            policy = get_policy(id)
        except LookupError as exc:
            return jsonify({"error": "not_found", "message": str(exc)}), 404
        return jsonify(_policy_dict(policy)), 200

    @blp.doc(
        summary="Update a draft policy (Admin)",
        security=[{"BearerAuth": []}],
    )
    @blp.arguments(PolicyUpdateSchema)
    @require_auth
    @require_role("admin")
    def patch(self, data, id):
        from app.services.policy_service import update_policy
        try:
            policy = update_policy(id, **data)
        except LookupError as exc:
            return jsonify({"error": "not_found", "message": str(exc)}), 404
        except ValueError as exc:
            if str(exc) == "policy_not_draft":
                return jsonify({"error": "conflict", "message": "Policy can only be updated in draft status"}), 409
            return jsonify({"error": "unprocessable_entity", "message": str(exc)}), 422
        return jsonify(_policy_dict(policy)), 200


@blp.route("/<int:id>/validate")
class PolicyValidateView(MethodView):
    @blp.doc(
        summary="Validate a draft policy (Admin)",
        security=[{"BearerAuth": []}],
    )
    @require_auth
    @require_role("admin")
    def post(self, id):
        from app.services.policy_service import validate_policy
        try:
            result = validate_policy(id)
        except LookupError as exc:
            return jsonify({"error": "not_found", "message": str(exc)}), 404
        return jsonify(result), 200


@blp.route("/<int:id>/activate")
class PolicyActivateView(MethodView):
    @blp.doc(
        summary="Activate a validated policy (Admin)",
        security=[{"BearerAuth": []}],
    )
    @require_auth
    @require_role("admin")
    def post(self, id):
        from app.services.policy_service import activate_policy
        user = g.current_user
        try:
            policy = activate_policy(id, activated_by=user.id)
        except LookupError as exc:
            return jsonify({"error": "not_found", "message": str(exc)}), 404
        except ValueError as exc:
            if str(exc) == "policy_not_validated":
                return jsonify({"error": "conflict", "message": "Policy must be in validated status to activate"}), 409
            return jsonify({"error": "unprocessable_entity", "message": str(exc)}), 422
        return jsonify(_policy_dict(policy)), 200


@blp.route("/<int:id>/canary")
class PolicyCanaryView(MethodView):
    @blp.doc(
        summary="Create a canary rollout for a policy (Admin)",
        security=[{"BearerAuth": []}],
    )
    @blp.arguments(CanarySchema)
    @require_auth
    @require_role("admin")
    def post(self, data, id):
        from app.services.policy_service import canary_rollout
        try:
            rollout = canary_rollout(
                policy_id=id,
                rollout_pct=data["rollout_pct"],
                segment=data.get("segment"),
            )
        except LookupError as exc:
            return jsonify({"error": "not_found", "message": str(exc)}), 404
        return jsonify({
            "policy_id": rollout.policy_id,
            "rollout_pct": rollout.rollout_pct,
            "segment": rollout.segment,
            "created_at": rollout.created_at.isoformat() if rollout.created_at else None,
        }), 200


@blp.route("/<int:id>/rollback")
class PolicyRollbackView(MethodView):
    @blp.doc(
        summary="Rollback an active policy to previous version (Admin)",
        security=[{"BearerAuth": []}],
    )
    @require_auth
    @require_role("admin")
    def post(self, id):
        from app.services.policy_service import rollback_policy
        user = g.current_user
        try:
            policy = rollback_policy(id, rolled_back_by=user.id)
        except LookupError as exc:
            return jsonify({"error": "not_found", "message": str(exc)}), 404
        return jsonify(_policy_dict(policy)), 200
