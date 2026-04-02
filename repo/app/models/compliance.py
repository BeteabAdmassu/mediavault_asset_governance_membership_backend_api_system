from datetime import datetime, timezone
from app.extensions import db

class DataRequest(db.Model):
    __tablename__ = "data_requests"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    type = db.Column(db.String(20), nullable=False)  # export, deletion
    status = db.Column(db.String(20), default="pending")  # pending, processing, complete, failed
    requested_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = db.Column(db.DateTime, nullable=True)
    notes = db.Column(db.Text, nullable=True)
