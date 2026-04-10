from datetime import datetime, timezone
from app.extensions import db

# DB-level allowlist — mirrors ALLOWED_POLICY_TYPES in policy_service.py.
# Kept as a module-level tuple so the CheckConstraint SQL can be built without
# importing from the service layer (avoids circular imports at model-load time).
_ALLOWED_POLICY_TYPES_SQL = (
    "booking",
    "course_selection",
    "warehouse_ops",
    "pricing",
    "risk",
    "rate_limit",
    "membership",
    "coupon",
)
_POLICY_TYPE_CHECK_SQL = "policy_type IN ({})".format(
    ",".join(f"'{t}'" for t in _ALLOWED_POLICY_TYPES_SQL)
)


class Policy(db.Model):
    __tablename__ = "policies"
    id = db.Column(db.Integer, primary_key=True)
    policy_type = db.Column(db.String(50), nullable=False)  # constrained — see CheckConstraint below
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

    __table_args__ = (
        db.CheckConstraint(_POLICY_TYPE_CHECK_SQL, name="ck_policies_policy_type"),
    )

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
