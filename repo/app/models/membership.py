from datetime import datetime, timezone
from app.extensions import db

class MembershipTier(db.Model):
    __tablename__ = "membership_tiers"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    min_points = db.Column(db.Integer, nullable=False, default=0)
    benefits = db.Column(db.Text, nullable=True)  # JSON
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

class Membership(db.Model):
    __tablename__ = "memberships"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    tier_id = db.Column(db.Integer, db.ForeignKey("membership_tiers.id"), nullable=True)
    points_balance = db.Column(db.Integer, default=0)
    stored_value_balance = db.Column(db.Integer, default=0)
    tier_since = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

class Ledger(db.Model):
    __tablename__ = "ledgers"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    amount = db.Column(db.Integer, nullable=False)  # cents/millionths, can be negative for debits
    currency = db.Column(db.String(20), nullable=False)  # points, stored_value
    entry_type = db.Column(db.String(20), nullable=False)  # credit, debit
    reason = db.Column(db.String(255), nullable=True)
    idempotency_key = db.Column(db.String(255), unique=True, nullable=False)
    reference_id = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (
        db.Index("ix_ledgers_user_currency", "user_id", "currency"),
    )
