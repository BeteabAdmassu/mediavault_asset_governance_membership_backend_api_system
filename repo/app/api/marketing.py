"""
Marketing API: Campaigns, Coupons, Incentive Validation, Redemptions.
"""
import flask_smorest
import marshmallow as ma
from flask import g, jsonify, request
from flask.views import MethodView

from app.utils.auth_utils import require_auth, require_role, get_user_rate_key
from app.extensions import limiter

blp = flask_smorest.Blueprint(
    "marketing",
    "marketing",
    url_prefix="/marketing",
    description="Campaigns, coupons, incentive validation, and redemptions",
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class CampaignCreateSchema(ma.Schema):
    name = ma.fields.Str(required=True)
    type = ma.fields.Str(required=True)
    start_at = ma.fields.DateTime(required=True)
    end_at = ma.fields.DateTime(required=True)
    benefit_type = ma.fields.Str(required=True)
    benefit_value = ma.fields.Int(required=True)
    max_redemptions = ma.fields.Int(load_default=None, allow_none=True)
    per_user_cap = ma.fields.Int(load_default=None, allow_none=True)
    min_order_cents = ma.fields.Int(load_default=None, allow_none=True)
    metadata = ma.fields.Dict(load_default=None, allow_none=True)


class CampaignUpdateSchema(ma.Schema):
    name = ma.fields.Str()
    type = ma.fields.Str()
    start_at = ma.fields.DateTime()
    end_at = ma.fields.DateTime()
    benefit_type = ma.fields.Str()
    benefit_value = ma.fields.Int()
    max_redemptions = ma.fields.Int(allow_none=True)
    per_user_cap = ma.fields.Int(allow_none=True)
    min_order_cents = ma.fields.Int(allow_none=True)


class CouponCreateSchema(ma.Schema):
    code = ma.fields.Str(required=True)
    campaign_id = ma.fields.Int(required=True)
    max_uses = ma.fields.Int(load_default=None, allow_none=True)
    per_user_cap = ma.fields.Int(load_default=None, allow_none=True)
    expires_at = ma.fields.DateTime(load_default=None, allow_none=True)


class ValidateIncentivesSchema(ma.Schema):
    user_id = ma.fields.Int(required=True)
    order_id = ma.fields.Str(required=True)
    order_cents = ma.fields.Int(required=True)
    coupon_codes = ma.fields.List(ma.fields.Str(), required=True)


class RedeemSchema(ma.Schema):
    user_id = ma.fields.Int(required=True)
    order_id = ma.fields.Str(required=True)
    coupon_codes = ma.fields.List(ma.fields.Str(), required=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _campaign_dict(campaign):
    return {
        "id": campaign.id,
        "name": campaign.name,
        "type": campaign.type,
        "start_at": campaign.start_at.isoformat() if campaign.start_at else None,
        "end_at": campaign.end_at.isoformat() if campaign.end_at else None,
        "benefit_type": campaign.benefit_type,
        "benefit_value": campaign.benefit_value,
        "max_redemptions": campaign.max_redemptions,
        "per_user_cap": campaign.per_user_cap,
        "min_order_cents": campaign.min_order_cents,
        "redemption_count": campaign.redemption_count,
        "deleted_at": campaign.deleted_at.isoformat() if campaign.deleted_at else None,
        "created_at": campaign.created_at.isoformat() if campaign.created_at else None,
    }


def _coupon_dict(coupon):
    return {
        "id": coupon.id,
        "code": coupon.code,
        "campaign_id": coupon.campaign_id,
        "max_uses": coupon.max_uses,
        "per_user_cap": coupon.per_user_cap,
        "expires_at": coupon.expires_at.isoformat() if coupon.expires_at else None,
        "created_at": coupon.created_at.isoformat() if coupon.created_at else None,
    }


def _redemption_dict(redemption):
    return {
        "id": redemption.id,
        "user_id": redemption.user_id,
        "coupon_id": redemption.coupon_id,
        "order_id": redemption.order_id,
        "redeemed_at": redemption.redeemed_at.isoformat() if redemption.redeemed_at else None,
    }


def _is_admin(user):
    return any(r.name == "admin" for r in user.roles)


# ---------------------------------------------------------------------------
# Campaign CRUD (Admin)
# ---------------------------------------------------------------------------

@blp.route("/campaigns")
class CampaignsView(MethodView):
    @blp.doc(
        summary="Create a new campaign (admin only)",
        security=[{"BearerAuth": []}],
    )
    @blp.arguments(CampaignCreateSchema)
    @require_auth
    @require_role("admin")
    def post(self, data):
        from app.services.marketing_service import create_campaign
        campaign = create_campaign(
            name=data["name"],
            type=data["type"],
            start_at=data["start_at"],
            end_at=data["end_at"],
            benefit_type=data["benefit_type"],
            benefit_value=data["benefit_value"],
            max_redemptions=data.get("max_redemptions"),
            per_user_cap=data.get("per_user_cap"),
            min_order_cents=data.get("min_order_cents"),
            metadata=data.get("metadata"),
        )
        return jsonify(_campaign_dict(campaign)), 201

    @blp.doc(
        summary="List active campaigns",
        security=[{"BearerAuth": []}],
    )
    @require_auth
    @require_role("admin")
    def get(self):
        from app.services.marketing_service import get_campaigns
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 20, type=int)
        pagination = get_campaigns(page=page, per_page=per_page)
        return jsonify({
            "items": [_campaign_dict(c) for c in pagination.items],
            "total": pagination.total,
            "page": pagination.page,
            "per_page": pagination.per_page,
            "pages": pagination.pages,
        }), 200


@blp.route("/campaigns/<int:id>")
class CampaignDetailView(MethodView):
    @blp.doc(
        summary="Get a campaign by ID (admin only)",
        security=[{"BearerAuth": []}],
    )
    @require_auth
    @require_role("admin")
    def get(self, id):
        from app.services.marketing_service import get_campaign
        try:
            campaign = get_campaign(id)
        except LookupError as exc:
            return jsonify({"error": "not_found", "message": str(exc)}), 404
        return jsonify(_campaign_dict(campaign)), 200

    @blp.doc(
        summary="Update a campaign (admin only)",
        security=[{"BearerAuth": []}],
    )
    @blp.arguments(CampaignUpdateSchema)
    @require_auth
    @require_role("admin")
    def patch(self, data, id):
        from app.services.marketing_service import update_campaign
        try:
            campaign = update_campaign(id, **data)
        except LookupError as exc:
            return jsonify({"error": "not_found", "message": str(exc)}), 404
        return jsonify(_campaign_dict(campaign)), 200

    @blp.doc(
        summary="Soft-delete a campaign (admin only)",
        security=[{"BearerAuth": []}],
    )
    @require_auth
    @require_role("admin")
    def delete(self, id):
        from app.services.marketing_service import delete_campaign
        try:
            delete_campaign(id)
        except LookupError as exc:
            return jsonify({"error": "not_found", "message": str(exc)}), 404
        return jsonify({"message": "Campaign deleted"}), 200


# ---------------------------------------------------------------------------
# Coupon CRUD (Admin)
# ---------------------------------------------------------------------------

@blp.route("/coupons")
class CouponsView(MethodView):
    @blp.doc(
        summary="Create a new coupon (admin only)",
        security=[{"BearerAuth": []}],
    )
    @blp.arguments(CouponCreateSchema)
    @require_auth
    @require_role("admin")
    def post(self, data):
        from app.services.marketing_service import create_coupon
        try:
            coupon = create_coupon(
                code=data["code"],
                campaign_id=data["campaign_id"],
                max_uses=data.get("max_uses"),
                per_user_cap=data.get("per_user_cap"),
                expires_at=data.get("expires_at"),
            )
        except ValueError as exc:
            return jsonify({"error": "conflict", "message": str(exc)}), 409
        except LookupError as exc:
            return jsonify({"error": "not_found", "message": str(exc)}), 404
        return jsonify(_coupon_dict(coupon)), 201

    @blp.doc(
        summary="List all coupons (admin only)",
        security=[{"BearerAuth": []}],
    )
    @require_auth
    @require_role("admin")
    def get(self):
        from app.services.marketing_service import get_coupons
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 20, type=int)
        pagination = get_coupons(page=page, per_page=per_page)
        return jsonify({
            "items": [_coupon_dict(c) for c in pagination.items],
            "total": pagination.total,
            "page": pagination.page,
            "per_page": pagination.per_page,
            "pages": pagination.pages,
        }), 200


@blp.route("/coupons/<int:id>")
class CouponDetailView(MethodView):
    @blp.doc(
        summary="Get a coupon by ID (admin only)",
        security=[{"BearerAuth": []}],
    )
    @require_auth
    @require_role("admin")
    def get(self, id):
        from app.services.marketing_service import get_coupon
        try:
            coupon = get_coupon(id)
        except LookupError as exc:
            return jsonify({"error": "not_found", "message": str(exc)}), 404
        return jsonify(_coupon_dict(coupon)), 200


# ---------------------------------------------------------------------------
# Validate incentives (authenticated user)
# ---------------------------------------------------------------------------

@blp.route("/validate-incentives")
class ValidateIncentivesView(MethodView):
    @blp.doc(
        summary="Validate coupon codes for an order",
        description="Validates up to 2 coupon codes for a given order. Returns discounts.",
        security=[{"BearerAuth": []}],
    )
    @blp.arguments(ValidateIncentivesSchema)
    @require_auth
    @limiter.limit("30/minute", key_func=get_user_rate_key)
    def post(self, data):
        from app.services.marketing_service import validate_incentives, ValidationError

        user = g.current_user
        requested_user_id = data["user_id"]

        # Object-level authorization: user_id must match current user OR admin
        if requested_user_id != user.id and not _is_admin(user):
            return jsonify({"error": "forbidden", "message": "Access denied: cannot validate for another user"}), 403

        try:
            result = validate_incentives(
                user_id=requested_user_id,
                order_id=data["order_id"],
                order_cents=data["order_cents"],
                coupon_codes=data["coupon_codes"],
            )
        except ValidationError as exc:
            return jsonify({
                "error": "validation_error",
                "message": str(exc),
                "details": exc.details,
            }), 422

        return jsonify(result), 200


# ---------------------------------------------------------------------------
# Redeem (authenticated)
# ---------------------------------------------------------------------------

@blp.route("/redeem")
class RedeemView(MethodView):
    @blp.doc(
        summary="Record coupon redemptions for an order",
        description="Records redemptions after order confirmation. Returns 201 or 409 on duplicate.",
        security=[{"BearerAuth": []}],
    )
    @blp.arguments(RedeemSchema)
    @require_auth
    @limiter.limit("30/minute", key_func=get_user_rate_key)
    def post(self, data):
        from app.services.marketing_service import record_redemption

        user = g.current_user
        requested_user_id = data["user_id"]

        # Object-level authorization: user_id must match current user OR admin
        if requested_user_id != user.id and not _is_admin(user):
            return jsonify({"error": "forbidden", "message": "Access denied: cannot redeem for another user"}), 403

        try:
            redemptions = record_redemption(
                user_id=requested_user_id,
                order_id=data["order_id"],
                coupon_codes=data["coupon_codes"],
            )
        except LookupError as exc:
            err_msg = str(exc)
            if "duplicate_redemption" in err_msg:
                return jsonify({"error": "conflict", "message": "Redemption already recorded for this order"}), 409
            return jsonify({"error": "not_found", "message": err_msg}), 404

        return jsonify([_redemption_dict(r) for r in redemptions]), 201


# ---------------------------------------------------------------------------
# Redemption log (Admin)
# ---------------------------------------------------------------------------

@blp.route("/redemptions")
class RedemptionsView(MethodView):
    @blp.doc(
        summary="List all redemptions (admin only)",
        security=[{"BearerAuth": []}],
    )
    @require_auth
    @require_role("admin")
    def get(self):
        from app.services.marketing_service import get_redemptions
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 20, type=int)
        pagination = get_redemptions(page=page, per_page=per_page)
        return jsonify({
            "items": [_redemption_dict(r) for r in pagination.items],
            "total": pagination.total,
            "page": pagination.page,
            "per_page": pagination.per_page,
            "pages": pagination.pages,
        }), 200
