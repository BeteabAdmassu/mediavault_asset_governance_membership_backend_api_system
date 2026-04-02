"""
Risk evaluation service for MediaVault.

Evaluates risk signals from DB state and returns a decision + reasons.
"""
from datetime import datetime, timezone, timedelta
import json

from sqlalchemy import func

from app.extensions import db
from app.models.risk import RiskEvent, Blacklist
from app.models.auth import LoginAttempt


# ---------------------------------------------------------------------------
# Default thresholds
# ---------------------------------------------------------------------------
THRESHOLDS = {
    "rapid_account_creation": {"count": 3, "window_minutes": 10, "severity": "HIGH"},
    "credential_stuffing":    {"count": 10, "window_minutes": 5,  "severity": "HIGH"},
    "reserve_abandon":        {"count": 4, "window_minutes": 60,  "severity": "MEDIUM"},
    "coupon_cycling":         {"count": 3, "window_minutes": 1440, "severity": "MEDIUM"},
    "high_velocity_profile_edit": {"count": 5, "window_minutes": 10, "severity": "HIGH"},
}


def _get_thresholds():
    """
    Return thresholds dict. Reads from active Policy if one exists, else returns
    hardcoded defaults. This keeps the design open for future policy overrides.
    """
    try:
        from app.models.policy import Policy, PolicyVersion
        policy = Policy.query.filter_by(name="risk_thresholds", status="active").first()
        if policy:
            version = (
                PolicyVersion.query
                .filter_by(policy_id=policy.id)
                .order_by(PolicyVersion.version.desc())
                .first()
            )
            if version and version.config_json:
                config = json.loads(version.config_json)
                if isinstance(config, dict) and "thresholds" in config:
                    return config["thresholds"]
    except Exception:
        pass
    return THRESHOLDS


# ---------------------------------------------------------------------------
# Individual signal evaluators
# ---------------------------------------------------------------------------

def _check_rapid_account_creation(ip, thresholds):
    if not ip:
        return False
    cfg = thresholds.get("rapid_account_creation", THRESHOLDS["rapid_account_creation"])
    window_start = datetime.now(timezone.utc) - timedelta(minutes=cfg["window_minutes"])
    count = db.session.query(func.count(RiskEvent.id)).filter(
        RiskEvent.event_type == "registration",
        RiskEvent.ip == ip,
        RiskEvent.created_at >= window_start,
    ).scalar() or 0
    return count >= cfg["count"]


def _check_credential_stuffing(ip, thresholds):
    if not ip:
        return False
    cfg = thresholds.get("credential_stuffing", THRESHOLDS["credential_stuffing"])
    window_start = datetime.now(timezone.utc) - timedelta(minutes=cfg["window_minutes"])
    distinct_users = db.session.query(
        func.count(func.distinct(LoginAttempt.user_id))
    ).filter(
        LoginAttempt.ip == ip,
        LoginAttempt.success == False,  # noqa: E712
        LoginAttempt.attempted_at >= window_start,
    ).scalar() or 0
    return distinct_users >= cfg["count"]


def _check_reserve_abandon(user_id, thresholds):
    if not user_id:
        return False
    cfg = thresholds.get("reserve_abandon", THRESHOLDS["reserve_abandon"])
    window_start = datetime.now(timezone.utc) - timedelta(minutes=cfg["window_minutes"])
    reserve_count = db.session.query(func.count(RiskEvent.id)).filter(
        RiskEvent.event_type == "reserve",
        RiskEvent.user_id == user_id,
        RiskEvent.created_at >= window_start,
    ).scalar() or 0
    checkout_count = db.session.query(func.count(RiskEvent.id)).filter(
        RiskEvent.event_type == "checkout",
        RiskEvent.user_id == user_id,
        RiskEvent.created_at >= window_start,
    ).scalar() or 0
    return (reserve_count - checkout_count) >= cfg["count"]


def _check_coupon_cycling(user_id, thresholds):
    if not user_id:
        return False
    cfg = thresholds.get("coupon_cycling", THRESHOLDS["coupon_cycling"])
    window_start = datetime.now(timezone.utc) - timedelta(minutes=cfg["window_minutes"])
    redeem_count = db.session.query(func.count(RiskEvent.id)).filter(
        RiskEvent.event_type == "coupon_redeem",
        RiskEvent.user_id == user_id,
        RiskEvent.created_at >= window_start,
    ).scalar() or 0
    refund_count = db.session.query(func.count(RiskEvent.id)).filter(
        RiskEvent.event_type == "coupon_refund",
        RiskEvent.user_id == user_id,
        RiskEvent.created_at >= window_start,
    ).scalar() or 0
    # Flag when there are >= threshold of both types (paired cycles)
    return redeem_count >= cfg["count"] and refund_count >= cfg["count"]


def _check_high_velocity_profile_edit(user_id, thresholds):
    if not user_id:
        return False
    cfg = thresholds.get("high_velocity_profile_edit", THRESHOLDS["high_velocity_profile_edit"])
    window_start = datetime.now(timezone.utc) - timedelta(minutes=cfg["window_minutes"])
    count = db.session.query(func.count(RiskEvent.id)).filter(
        RiskEvent.event_type == "profile_edit",
        RiskEvent.user_id == user_id,
        RiskEvent.created_at >= window_start,
    ).scalar() or 0
    return count >= cfg["count"]


# ---------------------------------------------------------------------------
# Main evaluation function
# ---------------------------------------------------------------------------

def evaluate_risk(event_type, ip, user_id=None, device_id=None, metadata=None):
    """
    Evaluate risk signals and return decision + reasons.

    Decision logic (first match wins):
    - Any HIGH signal fires  -> 'deny'
    - Any MEDIUM signal fires -> 'throttle'
    - Otherwise              -> 'allow'

    A RiskEvent row is always persisted after evaluation.

    Returns: {'decision': str, 'reasons': list}
    """
    thresholds = _get_thresholds()

    fired_high = []
    fired_medium = []

    # --- HIGH severity checks ---
    if _check_rapid_account_creation(ip, thresholds):
        fired_high.append("rapid_account_creation")

    if _check_credential_stuffing(ip, thresholds):
        fired_high.append("credential_stuffing")

    if _check_high_velocity_profile_edit(user_id, thresholds):
        fired_high.append("high_velocity_profile_edit")

    # --- MEDIUM severity checks ---
    if _check_reserve_abandon(user_id, thresholds):
        fired_medium.append("reserve_abandon")

    if _check_coupon_cycling(user_id, thresholds):
        fired_medium.append("coupon_cycling")

    # --- Decision ---
    if fired_high:
        decision = "deny"
        reasons = fired_high + fired_medium
    elif fired_medium:
        decision = "throttle"
        reasons = fired_medium
    else:
        decision = "allow"
        reasons = []

    # --- Persist the event ---
    event = RiskEvent(
        event_type=event_type,
        user_id=user_id,
        ip=ip,
        device_id=device_id,
        decision=decision,
        reasons=json.dumps(reasons),
        metadata_json=json.dumps(metadata) if metadata else None,
    )
    db.session.add(event)
    db.session.commit()

    return {"decision": decision, "reasons": reasons}
