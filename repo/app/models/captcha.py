from datetime import datetime, timezone
from app.extensions import db

class CaptchaChallenge(db.Model):
    __tablename__ = "captcha_challenges"
    id = db.Column(db.Integer, primary_key=True)
    question_key = db.Column(db.String(255), nullable=False)
    answer_hash = db.Column(db.String(255), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime, nullable=True)
    attempts = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

class CaptchaToken(db.Model):
    __tablename__ = "captcha_tokens"
    id = db.Column(db.String(36), primary_key=True)  # UUID
    challenge_id = db.Column(db.Integer, db.ForeignKey("captcha_challenges.id"), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
