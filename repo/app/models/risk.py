from datetime import datetime, timezone
from app.extensions import db

class RiskEvent(db.Model):
    __tablename__ = "risk_events"
    id = db.Column(db.Integer, primary_key=True)
    event_type = db.Column(db.String(50), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    ip = db.Column(db.String(45), nullable=True)
    device_id = db.Column(db.String(255), nullable=True)
    decision = db.Column(db.String(20), nullable=True)  # allow, challenge, throttle, deny
    reasons = db.Column(db.Text, nullable=True)  # JSON array
    metadata_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    __table_args__ = (
        db.Index("ix_risk_events_user_created", "user_id", "created_at"),
        db.Index("ix_risk_events_ip_created", "ip", "created_at"),
    )

class Blacklist(db.Model):
    __tablename__ = "blacklists"
    id = db.Column(db.Integer, primary_key=True)
    target_type = db.Column(db.String(20), nullable=False)  # user, device, ip
    target_id = db.Column(db.String(255), nullable=False)
    reason = db.Column(db.Text, nullable=False)
    start_at = db.Column(db.DateTime, nullable=False)
    end_at = db.Column(db.DateTime, nullable=True)
    reviewer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    appeal_status = db.Column(db.String(20), default="none")  # none, pending, approved, rejected
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
