from datetime import datetime, timezone
from app.extensions import db

class Taxonomy(db.Model):
    __tablename__ = "taxonomies"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    taxonomy_type = db.Column(db.String(20), nullable=False)  # category, tag
    parent_id = db.Column(db.Integer, db.ForeignKey("taxonomies.id"), nullable=True)
    level = db.Column(db.Integer, nullable=True)
    deleted_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

class Dictionary(db.Model):
    __tablename__ = "dictionaries"
    id = db.Column(db.Integer, primary_key=True)
    dimension = db.Column(db.String(50), nullable=False)  # keyword/topic/subject/audience/timeliness/source/copyright
    value = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    deleted_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

class Asset(db.Model):
    __tablename__ = "assets"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    asset_type = db.Column(db.String(20), nullable=False)  # image/video/document/audio
    category_id = db.Column(db.Integer, db.ForeignKey("taxonomies.id"), nullable=True)
    source = db.Column(db.String(255), nullable=True)
    copyright = db.Column(db.String(255), nullable=True)
    description = db.Column(db.Text, nullable=True)
    metadata_json = db.Column(db.Text, nullable=True)  # type-specific fields
    tags_json = db.Column(db.Text, nullable=True)
    keywords_json = db.Column(db.Text, nullable=True)
    topic = db.Column(db.String(255), nullable=True)
    subject = db.Column(db.String(255), nullable=True)
    audience = db.Column(db.String(255), nullable=True)
    timeliness = db.Column(db.String(255), nullable=True)
    is_restricted = db.Column(db.Boolean, default=False)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    deleted_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

class DownloadGrant(db.Model):
    __tablename__ = "download_grants"
    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(db.Integer, db.ForeignKey("assets.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    granted_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (db.UniqueConstraint("asset_id", "user_id"),)
