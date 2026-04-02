from datetime import datetime, timezone
from app.extensions import db

class Policy(db.Model):
    __tablename__ = "policies"
    id = db.Column(db.Integer, primary_key=True)
    policy_type = db.Column(db.String(50), nullable=False)  # booking/course_selection/warehouse_ops/pricing/risk/rate_limit/membership/coupon
    name = db.Column(db.String(255), nullable=False)
    semver = db.Column(db.String(20), nullable=False)  # MAJOR.MINOR.PATCH
    effective_from = db.Column(db.DateTime, nullable=False)
    effective_until = db.Column(db.DateTime, nullable=True)
    rules_json = db.Column(db.Text, nullable=False)
    description = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(30), default="draft")  # draft/pending_validation/validated/active/superseded/rolled_back
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

class PolicyVersion(db.Model):
    __tablename__ = "policy_versions"
    id = db.Column(db.Integer, primary_key=True)
    policy_id = db.Column(db.Integer, db.ForeignKey("policies.id"), nullable=False)
    from_status = db.Column(db.String(30), nullable=True)
    to_status = db.Column(db.String(30), nullable=False)
    changed_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    changed_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    notes = db.Column(db.Text, nullable=True)

class PolicyRollout(db.Model):
    __tablename__ = "policy_rollouts"
    id = db.Column(db.Integer, primary_key=True)
    policy_id = db.Column(db.Integer, db.ForeignKey("policies.id"), nullable=False)
    rollout_pct = db.Column(db.Integer, nullable=False)
    segment = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
