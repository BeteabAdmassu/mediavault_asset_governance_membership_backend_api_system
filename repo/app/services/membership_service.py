"""
Membership Tiers & Points Ledger service.
"""
import math
from datetime import datetime, timezone

from sqlalchemy import func, event

from app.extensions import db
from app.models.membership import Membership, MembershipTier, Ledger


# ---------------------------------------------------------------------------
# Ledger immutability guard
# ---------------------------------------------------------------------------

@event.listens_for(Ledger, "before_update")
def _block_ledger_update(mapper, connection, target):
    raise RuntimeError("Ledger entries are immutable")


# ---------------------------------------------------------------------------
# Tier management
# ---------------------------------------------------------------------------

def seed_default_tiers():
    """Create Basic (0 pts), Silver (500 pts), Gold (2000 pts) if not exist."""
    defaults = [
        {"name": "Basic", "min_points": 0, "benefits": "Basic membership benefits"},
        {"name": "Silver", "min_points": 500, "benefits": "Silver membership benefits"},
        {"name": "Gold", "min_points": 2000, "benefits": "Gold membership benefits"},
    ]
    for tier_data in defaults:
        existing = MembershipTier.query.filter_by(name=tier_data["name"]).first()
        if not existing:
            tier = MembershipTier(
                name=tier_data["name"],
                min_points=tier_data["min_points"],
                benefits=tier_data["benefits"],
            )
            db.session.add(tier)
    db.session.commit()


def create_tier(name, min_points, benefits):
    """Admin: create a new tier. Return tier."""
    existing = MembershipTier.query.filter_by(name=name).first()
    if existing:
        raise ValueError(f"Tier with name '{name}' already exists")

    tier = MembershipTier(
        name=name,
        min_points=min_points,
        benefits=benefits,
    )
    db.session.add(tier)
    db.session.commit()
    return tier


def get_tiers():
    """Return all tiers ordered by min_points."""
    return MembershipTier.query.order_by(MembershipTier.min_points.asc()).all()


def update_tier(tier_id, **kwargs):
    """Admin: update tier fields."""
    tier = MembershipTier.query.get(tier_id)
    if not tier:
        raise LookupError(f"Tier {tier_id} not found")
    for key, value in kwargs.items():
        if hasattr(tier, key):
            setattr(tier, key, value)
    db.session.commit()
    return tier


# ---------------------------------------------------------------------------
# Membership
# ---------------------------------------------------------------------------

def _get_or_create_membership(user_id):
    """Return existing membership or create one with Basic tier."""
    membership = Membership.query.filter_by(user_id=user_id).first()
    if not membership:
        basic_tier = MembershipTier.query.filter_by(name="Basic").first()
        membership = Membership(
            user_id=user_id,
            tier_id=basic_tier.id if basic_tier else None,
            points_balance=0,
            stored_value_balance=0,
            tier_since=datetime.now(timezone.utc),
        )
        db.session.add(membership)
        db.session.flush()
    return membership


def get_membership(user_id):
    """Return user's membership with tier info."""
    membership = Membership.query.filter_by(user_id=user_id).first()
    return membership


# ---------------------------------------------------------------------------
# Ledger operations
# ---------------------------------------------------------------------------

def _compute_balance(user_id, currency):
    """Compute balance from SUM of ledger entries (source of truth)."""
    total = db.session.query(func.sum(Ledger.amount)).filter(
        Ledger.user_id == user_id,
        Ledger.currency == currency,
    ).scalar() or 0
    return total


def credit_ledger(user_id, amount, currency, reason, idempotency_key, reference_id=None):
    """
    Admin/service: append credit entry.
    - Reject 409 if idempotency_key exists.
    - amount must be positive.
    - After credit, re-evaluate tier upgrade.
    Returns ledger entry.
    """
    if amount <= 0:
        raise ValueError("Amount must be positive")

    existing = Ledger.query.filter_by(idempotency_key=idempotency_key).first()
    if existing:
        raise LookupError("idempotency_key_conflict")

    entry = Ledger(
        user_id=user_id,
        amount=amount,
        currency=currency,
        entry_type="credit",
        reason=reason,
        idempotency_key=idempotency_key,
        reference_id=reference_id,
    )
    db.session.add(entry)
    db.session.flush()

    # Update points_balance cache if currency is points
    if currency == "points":
        membership = _get_or_create_membership(user_id)
        membership.points_balance = _compute_balance(user_id, "points")
        db.session.flush()

    db.session.commit()

    if currency == "points":
        evaluate_tier_upgrade(user_id)

    return entry


def debit_ledger(user_id, amount, currency, reason, idempotency_key, reference_id=None):
    """
    Admin/service: append debit entry.
    - Reject if balance would go negative (422).
    Returns ledger entry.
    """
    if amount <= 0:
        raise ValueError("Amount must be positive")

    existing = Ledger.query.filter_by(idempotency_key=idempotency_key).first()
    if existing:
        raise LookupError("idempotency_key_conflict")

    current_balance = _compute_balance(user_id, currency)
    if current_balance - amount < 0:
        raise ArithmeticError("Insufficient balance")

    entry = Ledger(
        user_id=user_id,
        amount=-amount,
        currency=currency,
        entry_type="debit",
        reason=reason,
        idempotency_key=idempotency_key,
        reference_id=reference_id,
    )
    db.session.add(entry)
    db.session.flush()

    # Update points_balance cache if currency is points
    if currency == "points":
        membership = _get_or_create_membership(user_id)
        membership.points_balance = _compute_balance(user_id, "points")
        db.session.flush()

    db.session.commit()
    return entry


def get_ledger(user_id, currency=None, date_from=None, date_to=None, page=1, per_page=20):
    """Return paginated ledger entries for user."""
    query = Ledger.query.filter_by(user_id=user_id)

    if currency:
        query = query.filter(Ledger.currency == currency)
    if date_from:
        query = query.filter(Ledger.created_at >= date_from)
    if date_to:
        query = query.filter(Ledger.created_at <= date_to)

    query = query.order_by(Ledger.created_at.desc())
    return query.paginate(page=page, per_page=per_page, error_out=False)


# ---------------------------------------------------------------------------
# Points accrual
# ---------------------------------------------------------------------------

def accrue_points(user_id, order_id, eligible_amount_cents):
    """
    Service: after confirmed spend.
    - Points = floor(eligible_amount_cents / 100)
    - Idempotency key = f"accrue:{order_id}"
    - Creates credit ledger entry.
    - Updates membership.points_balance cache.
    - Re-evaluates tier.
    """
    points = math.floor(eligible_amount_cents / 100)
    if points <= 0:
        raise ValueError("No points to accrue (eligible_amount_cents too small)")

    idempotency_key = f"accrue:{order_id}"

    entry = credit_ledger(
        user_id=user_id,
        amount=points,
        currency="points",
        reason=f"Points accrual for order {order_id}",
        idempotency_key=idempotency_key,
        reference_id=str(order_id),
    )
    return entry


# ---------------------------------------------------------------------------
# Tier evaluation
# ---------------------------------------------------------------------------

def evaluate_tier_upgrade(user_id):
    """
    After any ledger credit, check cumulative points vs tier thresholds.
    If threshold crossed, update memberships.tier_id and log audit.
    """
    total_points = db.session.query(func.sum(Ledger.amount)).filter(
        Ledger.user_id == user_id,
        Ledger.currency == "points",
    ).scalar() or 0

    tiers = MembershipTier.query.order_by(MembershipTier.min_points.desc()).all()
    new_tier = next((t for t in tiers if total_points >= t.min_points), None)

    if new_tier is None:
        return

    membership = Membership.query.filter_by(user_id=user_id).first()
    if membership is None:
        return

    if membership.tier_id != new_tier.id:
        old_tier_id = membership.tier_id
        membership.tier_id = new_tier.id
        membership.tier_since = datetime.now(timezone.utc)
        db.session.flush()

        # Log audit
        try:
            from app.services.audit_service import log_audit
            log_audit(
                actor_id=user_id,
                actor_role="system",
                action="tier_upgrade",
                entity_type="membership",
                entity_id=membership.id,
                detail={
                    "old_tier_id": old_tier_id,
                    "new_tier_id": new_tier.id,
                    "new_tier_name": new_tier.name,
                    "total_points": total_points,
                },
                ip="system",
            )
        except Exception:
            pass  # Don't fail tier upgrade if audit logging fails

        db.session.commit()
