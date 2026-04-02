"""
Membership Tiers & Points Ledger API blueprint.
"""
import flask_smorest
import marshmallow as ma
from flask import g, jsonify, request
from flask.views import MethodView

from app.utils.auth_utils import require_auth, require_role

blp = flask_smorest.Blueprint(
    "membership",
    "membership",
    url_prefix="/membership",
    description="Membership tiers, points ledger, and accrual",
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class TierSchema(ma.Schema):
    id = ma.fields.Int(dump_only=True)
    name = ma.fields.Str(required=True)
    min_points = ma.fields.Int(required=True)
    benefits = ma.fields.Str(allow_none=True)
    created_at = ma.fields.Str(dump_only=True)


class TierUpdateSchema(ma.Schema):
    name = ma.fields.Str()
    min_points = ma.fields.Int()
    benefits = ma.fields.Str(allow_none=True)


class MembershipMeSchema(ma.Schema):
    user_id = ma.fields.Int()
    tier_id = ma.fields.Int(allow_none=True)
    tier_name = ma.fields.Str(allow_none=True)
    points_balance = ma.fields.Int()
    stored_value_balance = ma.fields.Int()
    tier_since = ma.fields.Str(allow_none=True)


class LedgerEntrySchema(ma.Schema):
    id = ma.fields.Int(dump_only=True)
    user_id = ma.fields.Int()
    amount = ma.fields.Int()
    currency = ma.fields.Str()
    entry_type = ma.fields.Str()
    reason = ma.fields.Str(allow_none=True)
    idempotency_key = ma.fields.Str()
    reference_id = ma.fields.Str(allow_none=True)
    created_at = ma.fields.Str(dump_only=True)


class CreditDebitSchema(ma.Schema):
    user_id = ma.fields.Int(required=True)
    amount = ma.fields.Int(required=True)
    currency = ma.fields.Str(required=True)
    reason = ma.fields.Str(required=True)
    idempotency_key = ma.fields.Str(required=True)
    reference_id = ma.fields.Str(load_default=None)


class AccrueSchema(ma.Schema):
    user_id = ma.fields.Int(required=True)
    order_id = ma.fields.Str(required=True)
    eligible_amount_cents = ma.fields.Int(required=True)


class PaginatedLedgerSchema(ma.Schema):
    items = ma.fields.List(ma.fields.Nested(LedgerEntrySchema))
    total = ma.fields.Int()
    page = ma.fields.Int()
    per_page = ma.fields.Int()
    pages = ma.fields.Int()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _ledger_entry_dict(entry):
    return {
        "id": entry.id,
        "user_id": entry.user_id,
        "amount": entry.amount,
        "currency": entry.currency,
        "entry_type": entry.entry_type,
        "reason": entry.reason,
        "idempotency_key": entry.idempotency_key,
        "reference_id": entry.reference_id,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
    }


def _tier_dict(tier):
    return {
        "id": tier.id,
        "name": tier.name,
        "min_points": tier.min_points,
        "benefits": tier.benefits,
        "created_at": tier.created_at.isoformat() if tier.created_at else None,
    }


# ---------------------------------------------------------------------------
# Tier Management (Admin)
# ---------------------------------------------------------------------------

@blp.route("/tiers")
class TiersView(MethodView):
    @blp.doc(
        summary="List all membership tiers",
        description="Returns all tiers ordered by min_points.",
    )
    def get(self):
        from app.services.membership_service import get_tiers
        tiers = get_tiers()
        return jsonify([_tier_dict(t) for t in tiers]), 200

    @blp.doc(
        summary="Create a new membership tier (admin only)",
        description="Admin: create a new tier.",
        security=[{"BearerAuth": []}],
    )
    @blp.arguments(TierSchema)
    @require_auth
    @require_role("admin")
    def post(self, data):
        from app.services.membership_service import create_tier
        try:
            tier = create_tier(
                name=data["name"],
                min_points=data["min_points"],
                benefits=data.get("benefits"),
            )
        except ValueError as exc:
            return jsonify({"error": "conflict", "message": str(exc)}), 409
        return jsonify(_tier_dict(tier)), 201


@blp.route("/tiers/<int:id>")
class TierDetailView(MethodView):
    @blp.doc(
        summary="Update a membership tier (admin only)",
        description="Admin: update tier fields.",
        security=[{"BearerAuth": []}],
    )
    @blp.arguments(TierUpdateSchema)
    @require_auth
    @require_role("admin")
    def patch(self, data, id):
        from app.services.membership_service import update_tier
        try:
            tier = update_tier(id, **data)
        except LookupError as exc:
            return jsonify({"error": "not_found", "message": str(exc)}), 404
        return jsonify(_tier_dict(tier)), 200


# ---------------------------------------------------------------------------
# User Membership
# ---------------------------------------------------------------------------

@blp.route("/me")
class MembershipMeView(MethodView):
    @blp.doc(
        summary="Get current user's membership",
        description="Returns tier, points_balance, stored_value_balance, tier_since.",
        security=[{"BearerAuth": []}],
    )
    @require_auth
    def get(self):
        from app.services.membership_service import get_membership, _get_or_create_membership, _compute_balance
        from app.models.membership import MembershipTier
        from app.extensions import db

        user = g.current_user

        # Ensure membership exists
        with db.session.no_autoflush:
            membership = _get_or_create_membership(user.id)
            db.session.commit()

        membership = get_membership(user.id)
        tier_name = None
        if membership and membership.tier_id:
            tier = MembershipTier.query.get(membership.tier_id)
            tier_name = tier.name if tier else None

        # Use live balance from ledger as source of truth
        points_balance = _compute_balance(user.id, "points")
        stored_value_balance = _compute_balance(user.id, "stored_value")

        return jsonify({
            "user_id": user.id,
            "tier_id": membership.tier_id if membership else None,
            "tier_name": tier_name,
            "points_balance": points_balance,
            "stored_value_balance": stored_value_balance,
            "tier_since": membership.tier_since.isoformat() if membership and membership.tier_since else None,
        }), 200


# ---------------------------------------------------------------------------
# Ledger (Admin/service)
# ---------------------------------------------------------------------------

@blp.route("/ledger/credit")
class LedgerCreditView(MethodView):
    @blp.doc(
        summary="Credit a ledger entry (admin only)",
        description="Admin: append a credit entry to the ledger.",
        security=[{"BearerAuth": []}],
    )
    @blp.arguments(CreditDebitSchema)
    @require_auth
    @require_role("admin")
    def post(self, data):
        from app.services.membership_service import credit_ledger
        try:
            entry = credit_ledger(
                user_id=data["user_id"],
                amount=data["amount"],
                currency=data["currency"],
                reason=data["reason"],
                idempotency_key=data["idempotency_key"],
                reference_id=data.get("reference_id"),
            )
        except LookupError as exc:
            if "idempotency_key_conflict" in str(exc):
                return jsonify({"error": "conflict", "message": "Idempotency key already used"}), 409
            return jsonify({"error": "not_found", "message": str(exc)}), 404
        except ValueError as exc:
            return jsonify({"error": "unprocessable_entity", "message": str(exc)}), 422
        return jsonify(_ledger_entry_dict(entry)), 201


@blp.route("/ledger/debit")
class LedgerDebitView(MethodView):
    @blp.doc(
        summary="Debit a ledger entry (admin only)",
        description="Admin: append a debit entry to the ledger.",
        security=[{"BearerAuth": []}],
    )
    @blp.arguments(CreditDebitSchema)
    @require_auth
    @require_role("admin")
    def post(self, data):
        from app.services.membership_service import debit_ledger
        try:
            entry = debit_ledger(
                user_id=data["user_id"],
                amount=data["amount"],
                currency=data["currency"],
                reason=data["reason"],
                idempotency_key=data["idempotency_key"],
                reference_id=data.get("reference_id"),
            )
        except LookupError as exc:
            if "idempotency_key_conflict" in str(exc):
                return jsonify({"error": "conflict", "message": "Idempotency key already used"}), 409
            return jsonify({"error": "not_found", "message": str(exc)}), 404
        except ArithmeticError as exc:
            return jsonify({"error": "unprocessable_entity", "message": str(exc)}), 422
        except ValueError as exc:
            return jsonify({"error": "unprocessable_entity", "message": str(exc)}), 422
        return jsonify(_ledger_entry_dict(entry)), 201


@blp.route("/ledger")
class LedgerAdminView(MethodView):
    @blp.doc(
        summary="List ledger entries (admin only)",
        description="Admin: paginated, filterable ledger entries.",
        security=[{"BearerAuth": []}],
    )
    @require_auth
    @require_role("admin")
    def get(self):
        from app.services.membership_service import get_ledger

        user_id = request.args.get("user_id", type=int)
        currency = request.args.get("currency")
        date_from = request.args.get("date_from")
        date_to = request.args.get("date_to")
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 20, type=int)

        if user_id is None:
            return jsonify({"error": "bad_request", "message": "user_id is required"}), 400

        # Check: non-admin users cannot access other users' ledger
        # (admin-only route already enforces admin; this is the admin list view)
        pagination = get_ledger(
            user_id=user_id,
            currency=currency,
            date_from=date_from,
            date_to=date_to,
            page=page,
            per_page=per_page,
        )

        return jsonify({
            "items": [_ledger_entry_dict(e) for e in pagination.items],
            "total": pagination.total,
            "page": pagination.page,
            "per_page": pagination.per_page,
            "pages": pagination.pages,
        }), 200


@blp.route("/ledger/me")
class LedgerMeView(MethodView):
    @blp.doc(
        summary="Get own ledger entries (authenticated)",
        description="Self-scoped: returns the authenticated user's ledger entries.",
        security=[{"BearerAuth": []}],
    )
    @require_auth
    def get(self):
        from app.services.membership_service import get_ledger

        user = g.current_user
        currency = request.args.get("currency")
        date_from = request.args.get("date_from")
        date_to = request.args.get("date_to")
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 20, type=int)

        # IDOR check: if user_id param is provided and doesn't match current user (and not admin)
        requested_user_id = request.args.get("user_id", type=int)
        if requested_user_id is not None:
            is_admin = any(r.name == "admin" for r in user.roles)
            if requested_user_id != user.id and not is_admin:
                return jsonify({"error": "forbidden", "message": "Access denied"}), 403

        pagination = get_ledger(
            user_id=user.id,
            currency=currency,
            date_from=date_from,
            date_to=date_to,
            page=page,
            per_page=per_page,
        )

        return jsonify({
            "items": [_ledger_entry_dict(e) for e in pagination.items],
            "total": pagination.total,
            "page": pagination.page,
            "per_page": pagination.per_page,
            "pages": pagination.pages,
        }), 200


# ---------------------------------------------------------------------------
# Accrue
# ---------------------------------------------------------------------------

@blp.route("/accrue")
class AccrueView(MethodView):
    @blp.doc(
        summary="Accrue points for a user (admin/service only)",
        description="Admin: accrue points based on eligible spend amount.",
        security=[{"BearerAuth": []}],
    )
    @blp.arguments(AccrueSchema)
    @require_auth
    @require_role("admin")
    def post(self, data):
        from app.services.membership_service import accrue_points

        user = g.current_user

        try:
            entry = accrue_points(
                user_id=data["user_id"],
                order_id=data["order_id"],
                eligible_amount_cents=data["eligible_amount_cents"],
            )
        except LookupError as exc:
            if "idempotency_key_conflict" in str(exc):
                return jsonify({"error": "conflict", "message": "Points already accrued for this order"}), 409
            return jsonify({"error": "not_found", "message": str(exc)}), 404
        except ValueError as exc:
            return jsonify({"error": "unprocessable_entity", "message": str(exc)}), 422

        return jsonify(_ledger_entry_dict(entry)), 201
