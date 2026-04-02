from datetime import datetime, timezone
from app.extensions import db

class Campaign(db.Model):
    __tablename__ = "campaigns"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    type = db.Column(db.String(50), nullable=False)  # discount/spend_and_save/limited_time/limited_quantity
    start_at = db.Column(db.DateTime, nullable=False)
    end_at = db.Column(db.DateTime, nullable=False)
    max_redemptions = db.Column(db.Integer, nullable=True)
    per_user_cap = db.Column(db.Integer, nullable=True)
    benefit_type = db.Column(db.String(50), nullable=False)  # percent_off/fixed_off/free_item/stored_value_credit
    benefit_value = db.Column(db.Integer, nullable=False)
    min_order_cents = db.Column(db.Integer, nullable=True)
    metadata_json = db.Column(db.Text, nullable=True)
    redemption_count = db.Column(db.Integer, default=0)
    deleted_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

class Coupon(db.Model):
    __tablename__ = "coupons"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(100), unique=True, nullable=False)
    campaign_id = db.Column(db.Integer, db.ForeignKey("campaigns.id"), nullable=False)
    max_uses = db.Column(db.Integer, nullable=True)
    per_user_cap = db.Column(db.Integer, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

class CouponRedemption(db.Model):
    __tablename__ = "coupon_redemptions"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    coupon_id = db.Column(db.Integer, db.ForeignKey("coupons.id"), nullable=False)
    order_id = db.Column(db.String(255), nullable=False)
    redeemed_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (
        db.UniqueConstraint("user_id", "coupon_id", "order_id"),
        db.Index("ix_coupon_redemptions_user_coupon", "user_id", "coupon_id"),
    )
