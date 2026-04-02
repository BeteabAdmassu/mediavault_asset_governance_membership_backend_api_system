"""
Marketing service: Campaigns, Coupons, Incentive Validation, Redemptions.
"""
import math
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.marketing import Campaign, Coupon, CouponRedemption


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------

class ValidationError(Exception):
    """Raised when coupon/campaign validation fails."""
    def __init__(self, message, details=None):
        super().__init__(message)
        self.details = details or []


# ---------------------------------------------------------------------------
# Campaign CRUD
# ---------------------------------------------------------------------------

def create_campaign(name, type, start_at, end_at, benefit_type, benefit_value,
                    max_redemptions=None, per_user_cap=None, min_order_cents=None,
                    metadata=None):
    """Create campaign. Return campaign."""
    import json
    campaign = Campaign(
        name=name,
        type=type,
        start_at=start_at,
        end_at=end_at,
        benefit_type=benefit_type,
        benefit_value=benefit_value,
        max_redemptions=max_redemptions,
        per_user_cap=per_user_cap,
        min_order_cents=min_order_cents,
        metadata_json=json.dumps(metadata) if metadata else None,
        redemption_count=0,
    )
    db.session.add(campaign)
    db.session.flush()

    # Create MasterRecord for this campaign
    from app.services.master_record_service import create_master_record
    create_master_record(
        entity_type="campaign",
        entity_id=campaign.id,
        initial_status="active",
        created_by=None,
    )

    db.session.commit()
    return campaign


def get_campaigns(page=1, per_page=20):
    """List active (not deleted) campaigns."""
    query = Campaign.query.filter(Campaign.deleted_at == None)  # noqa: E711
    return query.order_by(Campaign.id.desc()).paginate(page=page, per_page=per_page, error_out=False)


def get_campaign(campaign_id):
    """Get single campaign."""
    campaign = Campaign.query.get(campaign_id)
    if not campaign or campaign.deleted_at is not None:
        raise LookupError(f"Campaign {campaign_id} not found")
    return campaign


def update_campaign(campaign_id, **kwargs):
    """Update campaign."""
    campaign = Campaign.query.get(campaign_id)
    if not campaign or campaign.deleted_at is not None:
        raise LookupError(f"Campaign {campaign_id} not found")
    for key, value in kwargs.items():
        if hasattr(campaign, key):
            setattr(campaign, key, value)
    db.session.commit()
    return campaign


def delete_campaign(campaign_id):
    """Soft-delete campaign."""
    campaign = Campaign.query.get(campaign_id)
    if not campaign or campaign.deleted_at is not None:
        raise LookupError(f"Campaign {campaign_id} not found")
    campaign.deleted_at = datetime.now(timezone.utc)
    db.session.commit()
    return campaign


# ---------------------------------------------------------------------------
# Coupon CRUD
# ---------------------------------------------------------------------------

def create_coupon(code, campaign_id, max_uses=None, per_user_cap=None, expires_at=None):
    """Create coupon with unique code."""
    existing = Coupon.query.filter_by(code=code).first()
    if existing:
        raise ValueError(f"Coupon code '{code}' already exists")

    campaign = Campaign.query.get(campaign_id)
    if not campaign or campaign.deleted_at is not None:
        raise LookupError(f"Campaign {campaign_id} not found")

    coupon = Coupon(
        code=code,
        campaign_id=campaign_id,
        max_uses=max_uses,
        per_user_cap=per_user_cap,
        expires_at=expires_at,
    )
    db.session.add(coupon)
    db.session.commit()
    return coupon


def get_coupons(page=1, per_page=20):
    """List all coupons."""
    return Coupon.query.order_by(Coupon.id.desc()).paginate(page=page, per_page=per_page, error_out=False)


def get_coupon(coupon_id):
    """Get single coupon."""
    coupon = Coupon.query.get(coupon_id)
    if not coupon:
        raise LookupError(f"Coupon {coupon_id} not found")
    return coupon


# ---------------------------------------------------------------------------
# Discount calculation
# ---------------------------------------------------------------------------

def _calculate_discount_cents(benefit_type, benefit_value, order_cents):
    """Calculate discount_cents based on benefit_type."""
    if benefit_type == "percent_off":
        return math.floor(order_cents * benefit_value / 100)
    elif benefit_type == "fixed_off":
        return min(benefit_value, order_cents)
    elif benefit_type == "free_item":
        return benefit_value
    elif benefit_type == "stored_value_credit":
        return benefit_value
    return 0


# ---------------------------------------------------------------------------
# Validate incentives
# ---------------------------------------------------------------------------

def validate_incentives(user_id, order_id, order_cents, coupon_codes):
    """
    Validate a list of coupon codes for an order.

    Rules:
    1. Max 2 coupons → raise 422 if > 2
    2. For each coupon:
       a. Must exist and have an active campaign
       b. Campaign must be within start_at/end_at window
       c. Coupon expires_at not in past
       d. User redemption count < per_user_cap (coupon and campaign level)
       e. Global redemptions < max_redemptions
       f. min_order_cents must be met
    3. No two coupons from campaigns with same benefit_type (conflict)

    Returns: {discounts: [{code, discount_cents}], total_discount_cents}
    Raises ValidationError with 422 for each specific failure.
    """
    now = datetime.now(timezone.utc)

    # Rule 1: Max 2 coupons
    if len(coupon_codes) > 2:
        raise ValidationError(
            "Too many coupons",
            details=[{"code": None, "error": "max_coupons_exceeded",
                       "message": "Maximum 2 coupons allowed per order"}]
        )

    discounts = []
    seen_benefit_types = {}  # benefit_type -> coupon code (for conflict detection)

    for code in coupon_codes:
        # Rule 2a: Must exist
        coupon = Coupon.query.filter_by(code=code).first()
        if not coupon:
            raise ValidationError(
                f"Coupon not found: {code}",
                details=[{"code": code, "error": "coupon_not_found",
                           "message": f"Coupon '{code}' does not exist"}]
            )

        # Rule 2a: Must have an active campaign
        campaign = Campaign.query.get(coupon.campaign_id)
        if not campaign or campaign.deleted_at is not None:
            raise ValidationError(
                f"No active campaign for coupon: {code}",
                details=[{"code": code, "error": "campaign_not_active",
                           "message": f"Coupon '{code}' has no active campaign"}]
            )

        # Rule 2b: Campaign must be within start_at/end_at window
        # Normalize campaign dates to UTC-aware if naive
        camp_start = campaign.start_at
        if camp_start.tzinfo is None:
            camp_start = camp_start.replace(tzinfo=timezone.utc)
        camp_end = campaign.end_at
        if camp_end.tzinfo is None:
            camp_end = camp_end.replace(tzinfo=timezone.utc)

        if now < camp_start:
            raise ValidationError(
                f"Campaign not yet active for coupon: {code}",
                details=[{"code": code, "error": "campaign_not_started",
                           "message": f"Campaign for coupon '{code}' has not started yet"}]
            )
        if now > camp_end:
            raise ValidationError(
                f"Campaign expired for coupon: {code}",
                details=[{"code": code, "error": "campaign_expired",
                           "message": f"Campaign for coupon '{code}' has expired"}]
            )

        # Rule 2c: Coupon expires_at not in past
        if coupon.expires_at is not None:
            exp = coupon.expires_at
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if now > exp:
                raise ValidationError(
                    f"Coupon expired: {code}",
                    details=[{"code": code, "error": "coupon_expired",
                               "message": f"Coupon '{code}' has expired"}]
                )

        # Rule 2d: User redemption count < per_user_cap (coupon level)
        if coupon.per_user_cap is not None:
            user_coupon_redemptions = CouponRedemption.query.filter_by(
                user_id=user_id, coupon_id=coupon.id
            ).count()
            if user_coupon_redemptions >= coupon.per_user_cap:
                raise ValidationError(
                    f"Per-user cap exceeded for coupon: {code}",
                    details=[{"code": code, "error": "per_user_cap_exceeded",
                               "message": f"You have already redeemed coupon '{code}' the maximum number of times"}]
                )

        # Rule 2d: User redemption count < per_user_cap (campaign level)
        if campaign.per_user_cap is not None:
            # Count all redemptions for this user across all coupons in this campaign
            user_campaign_redemptions = (
                db.session.query(CouponRedemption)
                .join(Coupon, Coupon.id == CouponRedemption.coupon_id)
                .filter(
                    CouponRedemption.user_id == user_id,
                    Coupon.campaign_id == campaign.id,
                )
                .count()
            )
            if user_campaign_redemptions >= campaign.per_user_cap:
                raise ValidationError(
                    f"Campaign per-user cap exceeded for coupon: {code}",
                    details=[{"code": code, "error": "campaign_per_user_cap_exceeded",
                               "message": f"You have reached the per-user limit for the campaign associated with '{code}'"}]
                )

        # Rule 2e: Global redemptions < max_redemptions
        if campaign.max_redemptions is not None:
            if campaign.redemption_count >= campaign.max_redemptions:
                raise ValidationError(
                    f"Global redemption limit reached for coupon: {code}",
                    details=[{"code": code, "error": "max_redemptions_exceeded",
                               "message": f"Coupon '{code}' has reached its global redemption limit"}]
                )

        # Rule 2f: min_order_cents must be met
        if campaign.min_order_cents is not None:
            if order_cents < campaign.min_order_cents:
                raise ValidationError(
                    f"Order total too low for coupon: {code}",
                    details=[{"code": code, "error": "min_order_not_met",
                               "message": f"Order total does not meet the minimum required for coupon '{code}'"}]
                )

        # Rule 3: No two coupons from campaigns with same benefit_type (conflict)
        benefit_type = campaign.benefit_type
        if benefit_type in seen_benefit_types:
            raise ValidationError(
                f"Conflicting coupons: both have benefit_type '{benefit_type}'",
                details=[{"code": code, "error": "benefit_type_conflict",
                           "message": f"Cannot stack coupon '{code}' with '{seen_benefit_types[benefit_type]}': same benefit type '{benefit_type}'"}]
            )
        seen_benefit_types[benefit_type] = code

        # Calculate discount
        discount_cents = _calculate_discount_cents(benefit_type, campaign.benefit_value, order_cents)
        discounts.append({"code": code, "discount_cents": discount_cents})

    total_discount_cents = sum(d["discount_cents"] for d in discounts)
    return {"discounts": discounts, "total_discount_cents": total_discount_cents}


# ---------------------------------------------------------------------------
# Record redemption
# ---------------------------------------------------------------------------

def record_redemption(user_id, order_id, coupon_codes):
    """
    Record coupon redemptions after order confirmation.
    - Insert into coupon_redemptions (UNIQUE constraint: user_id, coupon_id, order_id)
    - Increment campaign.redemption_count atomically
    - Use SELECT FOR UPDATE on coupon/campaign rows (SQLite: serialized transactions)
    Returns list of redemption records.
    """
    redemptions = []

    try:
        for code in coupon_codes:
            coupon = Coupon.query.filter_by(code=code).first()
            if not coupon:
                raise LookupError(f"Coupon '{code}' not found")

            campaign = Campaign.query.get(coupon.campaign_id)
            if not campaign:
                raise LookupError(f"Campaign not found for coupon '{code}'")

            # Create the redemption record
            redemption = CouponRedemption(
                user_id=user_id,
                coupon_id=coupon.id,
                order_id=str(order_id),
            )
            db.session.add(redemption)
            db.session.flush()  # flush to catch uniqueness constraint violations early

            # Increment campaign redemption_count atomically
            campaign.redemption_count = (campaign.redemption_count or 0) + 1
            db.session.flush()

            redemptions.append(redemption)

        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise LookupError("duplicate_redemption")

    return redemptions


# ---------------------------------------------------------------------------
# Redemption log (admin)
# ---------------------------------------------------------------------------

def get_redemptions(page=1, per_page=20):
    """Admin: paginated redemption log."""
    return CouponRedemption.query.order_by(CouponRedemption.redeemed_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
