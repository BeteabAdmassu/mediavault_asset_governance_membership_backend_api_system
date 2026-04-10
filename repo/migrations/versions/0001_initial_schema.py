"""Initial schema — all tables

Revision ID: 0001
Revises:
Create Date: 2026-04-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── roles ────────────────────────────────────────────────────────────────
    op.create_table(
        "roles",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(50), unique=True, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=True),
    )

    # ── users ────────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("username", sa.String(64), unique=True, nullable=False),
        sa.Column("email", sa.String(255), unique=True, nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), nullable=True),
        sa.Column("locked_until", sa.DateTime, nullable=True),
        sa.Column("anonymized_at", sa.DateTime, nullable=True),
        sa.Column("phone_encrypted", sa.Text, nullable=True),
        sa.Column("address_encrypted", sa.Text, nullable=True),
        sa.Column("dob_encrypted", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=True),
        sa.Column("updated_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_users_username", "users", ["username"])

    # ── user_roles ───────────────────────────────────────────────────────────
    op.create_table(
        "user_roles",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("role_id", sa.Integer, sa.ForeignKey("roles.id"), nullable=False),
        sa.Column("assigned_at", sa.DateTime, nullable=True),
        sa.UniqueConstraint("user_id", "role_id"),
    )

    # ── sessions ─────────────────────────────────────────────────────────────
    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token", sa.String(64), unique=True, nullable=False),
        sa.Column("expires_at", sa.DateTime, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=True),
        sa.Column("revoked_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_sessions_token", "sessions", ["token"])

    # ── login_attempts ───────────────────────────────────────────────────────
    op.create_table(
        "login_attempts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("ip", sa.String(45), nullable=True),
        sa.Column("attempted_at", sa.DateTime, nullable=True),
        sa.Column("success", sa.Boolean, nullable=True),
    )

    # ── risk_events ──────────────────────────────────────────────────────────
    op.create_table(
        "risk_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("ip", sa.String(45), nullable=True),
        sa.Column("device_id", sa.String(255), nullable=True),
        sa.Column("decision", sa.String(20), nullable=True),
        sa.Column("reasons", sa.Text, nullable=True),
        sa.Column("metadata_json", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_risk_events_user_created", "risk_events", ["user_id", "created_at"])
    op.create_index("ix_risk_events_ip_created", "risk_events", ["ip", "created_at"])

    # ── blacklists ───────────────────────────────────────────────────────────
    op.create_table(
        "blacklists",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("target_type", sa.String(20), nullable=False),
        sa.Column("target_id", sa.String(255), nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("start_at", sa.DateTime, nullable=False),
        sa.Column("end_at", sa.DateTime, nullable=True),
        sa.Column("reviewer_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("appeal_status", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=True),
    )

    # ── membership_tiers ─────────────────────────────────────────────────────
    op.create_table(
        "membership_tiers",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(50), unique=True, nullable=False),
        sa.Column("min_points", sa.Integer, nullable=False),
        sa.Column("benefits", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=True),
    )

    # ── memberships ──────────────────────────────────────────────────────────
    op.create_table(
        "memberships",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), unique=True, nullable=False),
        sa.Column("tier_id", sa.Integer, sa.ForeignKey("membership_tiers.id"), nullable=True),
        sa.Column("points_balance", sa.Integer, nullable=True),
        sa.Column("stored_value_balance", sa.Integer, nullable=True),
        sa.Column("tier_since", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=True),
        sa.Column("updated_at", sa.DateTime, nullable=True),
    )

    # ── ledgers ──────────────────────────────────────────────────────────────
    op.create_table(
        "ledgers",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("amount", sa.Integer, nullable=False),
        sa.Column("currency", sa.String(20), nullable=False),
        sa.Column("entry_type", sa.String(20), nullable=False),
        sa.Column("reason", sa.String(255), nullable=True),
        sa.Column("idempotency_key", sa.String(255), unique=True, nullable=False),
        sa.Column("reference_id", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_ledgers_user_currency", "ledgers", ["user_id", "currency"])

    # ── campaigns ────────────────────────────────────────────────────────────
    op.create_table(
        "campaigns",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("start_at", sa.DateTime, nullable=False),
        sa.Column("end_at", sa.DateTime, nullable=False),
        sa.Column("max_redemptions", sa.Integer, nullable=True),
        sa.Column("per_user_cap", sa.Integer, nullable=True),
        sa.Column("benefit_type", sa.String(50), nullable=False),
        sa.Column("benefit_value", sa.Integer, nullable=False),
        sa.Column("min_order_cents", sa.Integer, nullable=True),
        sa.Column("metadata_json", sa.Text, nullable=True),
        sa.Column("redemption_count", sa.Integer, nullable=True),
        sa.Column("deleted_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=True),
    )

    # ── coupons ──────────────────────────────────────────────────────────────
    op.create_table(
        "coupons",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("code", sa.String(100), unique=True, nullable=False),
        sa.Column("campaign_id", sa.Integer, sa.ForeignKey("campaigns.id"), nullable=False),
        sa.Column("max_uses", sa.Integer, nullable=True),
        sa.Column("per_user_cap", sa.Integer, nullable=True),
        sa.Column("expires_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=True),
    )

    # ── coupon_redemptions ───────────────────────────────────────────────────
    op.create_table(
        "coupon_redemptions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("coupon_id", sa.Integer, sa.ForeignKey("coupons.id"), nullable=False),
        sa.Column("order_id", sa.String(255), nullable=False),
        sa.Column("redeemed_at", sa.DateTime, nullable=True),
        sa.UniqueConstraint("user_id", "coupon_id", "order_id"),
    )
    op.create_index("ix_coupon_redemptions_user_coupon", "coupon_redemptions", ["user_id", "coupon_id"])

    # ── taxonomies ───────────────────────────────────────────────────────────
    op.create_table(
        "taxonomies",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("taxonomy_type", sa.String(20), nullable=False),
        sa.Column("parent_id", sa.Integer, sa.ForeignKey("taxonomies.id"), nullable=True),
        sa.Column("level", sa.Integer, nullable=True),
        sa.Column("deleted_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=True),
    )

    # ── dictionaries ─────────────────────────────────────────────────────────
    op.create_table(
        "dictionaries",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("dimension", sa.String(50), nullable=False),
        sa.Column("value", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("deleted_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=True),
    )

    # ── assets ───────────────────────────────────────────────────────────────
    op.create_table(
        "assets",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("asset_type", sa.String(20), nullable=False),
        sa.Column("category_id", sa.Integer, sa.ForeignKey("taxonomies.id"), nullable=True),
        sa.Column("source", sa.String(255), nullable=True),
        sa.Column("copyright", sa.String(255), nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("metadata_json", sa.Text, nullable=True),
        sa.Column("tags_json", sa.Text, nullable=True),
        sa.Column("keywords_json", sa.Text, nullable=True),
        sa.Column("topic", sa.String(255), nullable=True),
        sa.Column("subject", sa.String(255), nullable=True),
        sa.Column("audience", sa.String(255), nullable=True),
        sa.Column("timeliness", sa.String(255), nullable=True),
        sa.Column("is_restricted", sa.Boolean, nullable=True),
        sa.Column("created_by", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("deleted_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=True),
        sa.Column("updated_at", sa.DateTime, nullable=True),
    )

    # ── download_grants ──────────────────────────────────────────────────────
    op.create_table(
        "download_grants",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("asset_id", sa.Integer, sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("granted_by", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=True),
        sa.UniqueConstraint("asset_id", "user_id"),
    )

    # ── visibility_groups ────────────────────────────────────────────────────
    op.create_table(
        "visibility_groups",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("owner_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=True),
    )

    # ── visibility_group_members ─────────────────────────────────────────────
    op.create_table(
        "visibility_group_members",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("group_id", sa.Integer, sa.ForeignKey("visibility_groups.id"), nullable=False),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("added_at", sa.DateTime, nullable=True),
        sa.UniqueConstraint("group_id", "user_id"),
    )

    # ── profiles ─────────────────────────────────────────────────────────────
    op.create_table(
        "profiles",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), unique=True, nullable=False),
        sa.Column("display_name", sa.String(100), nullable=True),
        sa.Column("bio", sa.String(500), nullable=True),
        sa.Column("interest_tags_json", sa.Text, nullable=True),
        sa.Column("media_references_json", sa.Text, nullable=True),
        sa.Column("visibility_scope", sa.String(20), nullable=True),
        sa.Column("visibility_group_id", sa.Integer, sa.ForeignKey("visibility_groups.id"), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=True),
        sa.Column("updated_at", sa.DateTime, nullable=True),
    )

    # ── profile_follows ──────────────────────────────────────────────────────
    op.create_table(
        "profile_follows",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("follower_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("followee_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=True),
        sa.UniqueConstraint("follower_id", "followee_id"),
    )

    # ── profile_blocks ───────────────────────────────────────────────────────
    op.create_table(
        "profile_blocks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("blocker_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("blocked_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=True),
        sa.UniqueConstraint("blocker_id", "blocked_id"),
    )

    # ── profile_hides ────────────────────────────────────────────────────────
    op.create_table(
        "profile_hides",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("hider_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("hidden_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=True),
        sa.UniqueConstraint("hider_id", "hidden_id"),
    )

    # ── captcha_challenges ───────────────────────────────────────────────────
    op.create_table(
        "captcha_challenges",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("question_key", sa.String(255), nullable=False),
        sa.Column("answer_hash", sa.String(255), nullable=False),
        sa.Column("expires_at", sa.DateTime, nullable=False),
        sa.Column("used_at", sa.DateTime, nullable=True),
        sa.Column("attempts", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=True),
    )

    # ── captcha_tokens ───────────────────────────────────────────────────────
    op.create_table(
        "captcha_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("challenge_id", sa.Integer, sa.ForeignKey("captcha_challenges.id"), nullable=False),
        sa.Column("expires_at", sa.DateTime, nullable=False),
        sa.Column("used_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=True),
    )

    # ── policies ─────────────────────────────────────────────────────────────
    op.create_table(
        "policies",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("policy_type", sa.String(50), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("semver", sa.String(20), nullable=False),
        sa.Column("effective_from", sa.DateTime, nullable=False),
        sa.Column("effective_until", sa.DateTime, nullable=True),
        sa.Column("rules_json", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("status", sa.String(30), nullable=True),
        sa.Column("created_by", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=True),
        sa.Column("updated_at", sa.DateTime, nullable=True),
    )

    # ── policy_versions ──────────────────────────────────────────────────────
    op.create_table(
        "policy_versions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("policy_id", sa.Integer, sa.ForeignKey("policies.id"), nullable=False),
        sa.Column("from_status", sa.String(30), nullable=True),
        sa.Column("to_status", sa.String(30), nullable=False),
        sa.Column("changed_by", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("changed_at", sa.DateTime, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
    )

    # ── policy_rollouts ──────────────────────────────────────────────────────
    op.create_table(
        "policy_rollouts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("policy_id", sa.Integer, sa.ForeignKey("policies.id"), nullable=False),
        sa.Column("rollout_pct", sa.Integer, nullable=False),
        sa.Column("segment", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=True),
    )

    # ── data_requests ────────────────────────────────────────────────────────
    op.create_table(
        "data_requests",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=True),
        sa.Column("requested_at", sa.DateTime, nullable=True),
        sa.Column("completed_at", sa.DateTime, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
    )

    # ── master_records ───────────────────────────────────────────────────────
    op.create_table(
        "master_records",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", sa.Integer, nullable=False),
        sa.Column("current_status", sa.String(50), nullable=True),
        sa.Column("created_by", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=True),
        sa.Column("updated_at", sa.DateTime, nullable=True),
        sa.UniqueConstraint("entity_type", "entity_id"),
    )

    # ── master_record_history ────────────────────────────────────────────────
    op.create_table(
        "master_record_history",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("master_record_id", sa.Integer, sa.ForeignKey("master_records.id"), nullable=False),
        sa.Column("from_status", sa.String(50), nullable=True),
        sa.Column("to_status", sa.String(50), nullable=False),
        sa.Column("changed_by", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("changed_at", sa.DateTime, nullable=True),
        sa.Column("snapshot_json", sa.Text, nullable=True),
        sa.Column("reason", sa.Text, nullable=True),
    )

    # ── audit_logs ───────────────────────────────────────────────────────────
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("actor_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("actor_role", sa.String(50), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=True),
        sa.Column("entity_id", sa.Integer, nullable=True),
        sa.Column("detail_json", sa.Text, nullable=True),
        sa.Column("ip", sa.String(45), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_audit_logs_actor_created", "audit_logs", ["actor_id", "created_at"])


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("master_record_history")
    op.drop_table("master_records")
    op.drop_table("data_requests")
    op.drop_table("policy_rollouts")
    op.drop_table("policy_versions")
    op.drop_table("policies")
    op.drop_table("captcha_tokens")
    op.drop_table("captcha_challenges")
    op.drop_table("profile_hides")
    op.drop_table("profile_blocks")
    op.drop_table("profile_follows")
    op.drop_table("profiles")
    op.drop_table("visibility_group_members")
    op.drop_table("visibility_groups")
    op.drop_table("download_grants")
    op.drop_table("assets")
    op.drop_table("dictionaries")
    op.drop_table("taxonomies")
    op.drop_table("coupon_redemptions")
    op.drop_table("coupons")
    op.drop_table("campaigns")
    op.drop_table("ledgers")
    op.drop_table("memberships")
    op.drop_table("membership_tiers")
    op.drop_table("blacklists")
    op.drop_table("risk_events")
    op.drop_table("login_attempts")
    op.drop_table("sessions")
    op.drop_table("user_roles")
    op.drop_table("users")
    op.drop_table("roles")
