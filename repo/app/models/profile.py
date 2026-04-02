from datetime import datetime, timezone
from app.extensions import db

class Profile(db.Model):
    __tablename__ = "profiles"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    display_name = db.Column(db.String(100), nullable=True)
    bio = db.Column(db.String(500), nullable=True)
    interest_tags_json = db.Column(db.Text, nullable=True)
    media_references_json = db.Column(db.Text, nullable=True)
    visibility_scope = db.Column(db.String(20), default="public")  # public/mutual_followers/custom_group
    visibility_group_id = db.Column(db.Integer, db.ForeignKey("visibility_groups.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

class VisibilityGroup(db.Model):
    __tablename__ = "visibility_groups"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

class VisibilityGroupMember(db.Model):
    __tablename__ = "visibility_group_members"
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey("visibility_groups.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    added_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (db.UniqueConstraint("group_id", "user_id"),)

class ProfileFollow(db.Model):
    __tablename__ = "profile_follows"
    id = db.Column(db.Integer, primary_key=True)
    follower_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    followee_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (db.UniqueConstraint("follower_id", "followee_id"),)

class ProfileBlock(db.Model):
    __tablename__ = "profile_blocks"
    id = db.Column(db.Integer, primary_key=True)
    blocker_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    blocked_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (db.UniqueConstraint("blocker_id", "blocked_id"),)

class ProfileHide(db.Model):
    __tablename__ = "profile_hides"
    id = db.Column(db.Integer, primary_key=True)
    hider_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    hidden_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (db.UniqueConstraint("hider_id", "hidden_id"),)
