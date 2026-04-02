from datetime import datetime, timezone
from sqlalchemy import event
from app.extensions import db

class MasterRecord(db.Model):
    __tablename__ = "master_records"
    id = db.Column(db.Integer, primary_key=True)
    entity_type = db.Column(db.String(50), nullable=False)  # user/asset/policy/campaign/blacklist
    entity_id = db.Column(db.Integer, nullable=False)
    current_status = db.Column(db.String(50), nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    __table_args__ = (db.UniqueConstraint("entity_type", "entity_id"),)

class MasterRecordHistory(db.Model):
    __tablename__ = "master_record_history"
    id = db.Column(db.Integer, primary_key=True)
    master_record_id = db.Column(db.Integer, db.ForeignKey("master_records.id"), nullable=False)
    from_status = db.Column(db.String(50), nullable=True)
    to_status = db.Column(db.String(50), nullable=False)
    changed_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    changed_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    snapshot_json = db.Column(db.Text, nullable=True)
    reason = db.Column(db.Text, nullable=True)

@event.listens_for(MasterRecordHistory, "before_update")
def prevent_history_update(mapper, connection, target):
    raise RuntimeError("MasterRecordHistory rows are immutable")


class AuditLog(db.Model):
    __tablename__ = "audit_logs"
    id = db.Column(db.Integer, primary_key=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    actor_role = db.Column(db.String(50), nullable=True)
    action = db.Column(db.String(100), nullable=False)
    entity_type = db.Column(db.String(50), nullable=True)
    entity_id = db.Column(db.Integer, nullable=True)
    detail_json = db.Column(db.Text, nullable=True)
    ip = db.Column(db.String(45), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (
        db.Index("ix_audit_logs_actor_created", "actor_id", "created_at"),
    )
