"""
Policy Rules Engine service.
"""
import hashlib
import json
import os

import jsonschema

from app.extensions import db
from app.models.policy import Policy, PolicyVersion, PolicyRollout


# ---------------------------------------------------------------------------
# Policy type allowlist
# ---------------------------------------------------------------------------

ALLOWED_POLICY_TYPES = {
    "booking",
    "course_selection",
    "warehouse_ops",
    "pricing",
    "risk",
    "rate_limit",
    "membership",
    "coupon",
}


def validate_policy_type(policy_type):
    """Raise ValueError with code 'invalid_policy_type' if not in the allowlist."""
    if policy_type not in ALLOWED_POLICY_TYPES:
        raise ValueError(
            f"invalid_policy_type: {policy_type!r} is not a recognised policy type. "
            f"Allowed values: {sorted(ALLOWED_POLICY_TYPES)}"
        )


# ---------------------------------------------------------------------------
# Semver helpers
# ---------------------------------------------------------------------------

def parse_semver(semver_str):
    """Parse 'MAJOR.MINOR.PATCH' -> tuple (major, minor, patch)."""
    parts = semver_str.split(".")
    return tuple(int(p) for p in parts)


def semver_gt(a, b):
    """Return True if semver string a > b."""
    return parse_semver(a) > parse_semver(b)


# ---------------------------------------------------------------------------
# Schema validation helpers
# ---------------------------------------------------------------------------

def load_policy_schema(policy_type):
    schema_path = os.path.join(
        os.path.dirname(__file__), "..", "data", "policy_schemas", f"{policy_type}.json"
    )
    with open(schema_path) as f:
        return json.load(f)


def validate_rules_json(policy_type, rules_json_str):
    """
    Validate a rules_json string against the schema for policy_type.
    Returns a list of error messages (empty list means valid).
    """
    try:
        rules = json.loads(rules_json_str)
        schema = load_policy_schema(policy_type)
        jsonschema.validate(rules, schema)
        return []
    except jsonschema.ValidationError as e:
        return [e.message]
    except json.JSONDecodeError as e:
        return [f"Invalid JSON: {e}"]


# ---------------------------------------------------------------------------
# Canary helpers
# ---------------------------------------------------------------------------

def is_in_canary(user_id, rollout_pct):
    """Deterministically determine if a user is in a canary rollout."""
    hash_val = int(hashlib.md5(str(user_id).encode()).hexdigest(), 16)
    return (hash_val % 100) < rollout_pct


# ---------------------------------------------------------------------------
# Policy version history helper
# ---------------------------------------------------------------------------

def _append_version(policy_id, from_status, to_status, changed_by=None, notes=None):
    """Append a row to policy_versions."""
    pv = PolicyVersion(
        policy_id=policy_id,
        from_status=from_status,
        to_status=to_status,
        changed_by=changed_by,
        notes=notes,
    )
    db.session.add(pv)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def create_policy(policy_type, name, semver, effective_from, rules_json,
                  created_by, effective_until=None, description=None):
    """Create a policy in 'draft' status. Return the Policy object."""
    validate_policy_type(policy_type)
    policy = Policy(
        policy_type=policy_type,
        name=name,
        semver=semver,
        effective_from=effective_from,
        effective_until=effective_until,
        rules_json=rules_json,
        description=description,
        status="draft",
        created_by=created_by,
    )
    db.session.add(policy)
    db.session.flush()
    _append_version(policy.id, None, "draft", changed_by=created_by, notes="created")

    # Create MasterRecord for this policy
    from app.services.master_record_service import create_master_record
    create_master_record(
        entity_type="policy",
        entity_id=policy.id,
        initial_status="draft",
        created_by=created_by,
    )

    db.session.commit()
    return policy


def get_policies(policy_type=None, page=1, per_page=20):
    """List policies, optionally filtered by type. Returns a pagination object."""
    query = Policy.query
    if policy_type:
        query = query.filter_by(policy_type=policy_type)
    query = query.order_by(Policy.created_at.desc())
    return query.paginate(page=page, per_page=per_page, error_out=False)


def get_policy(policy_id):
    """Get a single policy by ID. Raises LookupError if not found."""
    policy = db.session.get(Policy, policy_id)
    if policy is None:
        raise LookupError(f"Policy {policy_id} not found")
    return policy


def update_policy(policy_id, **kwargs):
    """
    Update a policy. Only allowed if status='draft'.
    Raises ValueError (409-style) if not draft.
    """
    policy = get_policy(policy_id)
    if policy.status != "draft":
        raise ValueError("policy_not_draft")
    for key, value in kwargs.items():
        if hasattr(policy, key) and value is not None:
            setattr(policy, key, value)
    db.session.commit()
    return policy


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_policy(policy_id):
    """
    Pre-publish checks:
    1. rules_json validates against schema for policy_type
    2. semver is strictly higher than latest active version of same type
    Returns dict: {valid: True} or {valid: False, errors: []}
    Updates status: draft -> pending_validation -> validated (or back to draft on failure)
    """
    policy = get_policy(policy_id)
    errors = []

    # Move to pending_validation
    prev_status = policy.status
    policy.status = "pending_validation"
    db.session.flush()

    # 1. Validate rules_json against schema
    schema_errors = validate_rules_json(policy.policy_type, policy.rules_json)
    errors.extend(schema_errors)

    # 2. Semver must be strictly higher than any active version of same type
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    active_policy = (
        Policy.query
        .filter_by(policy_type=policy.policy_type, status="active")
        .first()
    )
    if active_policy and active_policy.id != policy_id:
        if not semver_gt(policy.semver, active_policy.semver):
            errors.append(
                f"semver {policy.semver!r} must be strictly higher than active "
                f"version {active_policy.semver!r}"
            )

    # 3. Effective window validity checks
    eff_from = policy.effective_from
    eff_until = policy.effective_until

    if eff_until is not None:
        eff_until_aware = (
            eff_until if eff_until.tzinfo else eff_until.replace(tzinfo=timezone.utc)
        )
        if eff_until_aware <= now:
            errors.append(
                f"effective_until {eff_until.isoformat()!r} is already in the past"
            )

    if eff_from is not None and eff_until is not None:
        eff_from_aware = (
            eff_from if eff_from.tzinfo else eff_from.replace(tzinfo=timezone.utc)
        )
        eff_until_aware = (
            eff_until if eff_until.tzinfo else eff_until.replace(tzinfo=timezone.utc)
        )
        if eff_from_aware >= eff_until_aware:
            errors.append("effective_from must be strictly before effective_until")

    # 4. Effective window conflict with currently active policy of same type
    if active_policy and active_policy.id != policy_id and active_policy.effective_until is not None and eff_from is not None:
        active_until_aware = (
            active_policy.effective_until
            if active_policy.effective_until.tzinfo
            else active_policy.effective_until.replace(tzinfo=timezone.utc)
        )
        eff_from_aware = (
            eff_from if eff_from.tzinfo else eff_from.replace(tzinfo=timezone.utc)
        )
        if eff_from_aware < active_until_aware:
            errors.append(
                f"effective_from overlaps with active policy {active_policy.id} "
                f"(active until {active_policy.effective_until.isoformat()})"
            )

    if errors:
        # Revert to draft
        policy.status = prev_status
        db.session.commit()
        return {"valid": False, "errors": errors}

    # All checks passed -> validated
    _append_version(policy.id, "pending_validation", "validated", notes="validation passed")
    policy.status = "validated"
    db.session.commit()
    return {"valid": True}


# ---------------------------------------------------------------------------
# Activation
# ---------------------------------------------------------------------------

def activate_policy(policy_id, activated_by):
    """
    Requires status='validated'.
    Sets status='active'.
    Previous active version of same type -> 'superseded'.
    Appends audit log and policy_versions rows.
    """
    policy = get_policy(policy_id)
    if policy.status != "validated":
        raise ValueError("policy_not_validated")

    # Supersede previous active version
    prev_active = (
        Policy.query
        .filter_by(policy_type=policy.policy_type, status="active")
        .first()
    )
    if prev_active and prev_active.id != policy_id:
        prev_active.status = "superseded"
        _append_version(prev_active.id, "active", "superseded",
                        changed_by=activated_by, notes=f"superseded by policy {policy_id}")

    policy.status = "active"
    _append_version(policy.id, "validated", "active",
                    changed_by=activated_by, notes="activated")

    # Audit log
    from app.services.audit_service import log_audit
    log_audit(
        actor_id=activated_by,
        actor_role="admin",
        action="policy_activate",
        entity_type="policy",
        entity_id=policy_id,
        detail={"semver": policy.semver, "policy_type": policy.policy_type},
        ip=None,
    )

    db.session.commit()
    return policy


# ---------------------------------------------------------------------------
# Canary rollout
# ---------------------------------------------------------------------------

def canary_rollout(policy_id, rollout_pct, segment=None):
    """
    Partial activation for rollout_pct% of users.
    Creates PolicyRollout row.
    Transitions status from 'validated' -> 'active' when applicable.

    Lifecycle requirement: policy must be in 'validated' or 'active' status.
    Draft and pending_validation policies are rejected (ValueError) to prevent
    unvalidated rules from reaching users via the canary path.  The API layer
    maps this ValueError to a 409 Conflict response.
    """
    policy = get_policy(policy_id)

    if policy.status not in ("validated", "active"):
        raise ValueError("canary_requires_validated_policy")

    rollout = PolicyRollout(
        policy_id=policy_id,
        rollout_pct=rollout_pct,
        segment=segment,
    )
    db.session.add(rollout)

    if policy.status != "active":
        prev_status = policy.status
        policy.status = "active"
        _append_version(policy.id, prev_status, "active", notes=f"canary rollout {rollout_pct}%")

    db.session.commit()
    return rollout


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------

def rollback_policy(policy_id, rolled_back_by):
    """
    One-click rollback:
    - Set this version status='rolled_back'
    - Find previous 'superseded' version of same type -> set back to 'active'
    - Log audit event with action='policy_rollback'
    - Append policy_versions rows
    """
    policy = get_policy(policy_id)

    prev_status = policy.status
    policy.status = "rolled_back"
    _append_version(policy.id, prev_status, "rolled_back",
                    changed_by=rolled_back_by, notes="rolled back")

    # Find the most recent superseded version of the same type
    prev_superseded = (
        Policy.query
        .filter_by(policy_type=policy.policy_type, status="superseded")
        .order_by(Policy.updated_at.desc())
        .first()
    )
    if prev_superseded:
        prev_superseded.status = "active"
        _append_version(prev_superseded.id, "superseded", "active",
                        changed_by=rolled_back_by, notes=f"restored after rollback of {policy_id}")

    # Audit log
    from app.services.audit_service import log_audit
    log_audit(
        actor_id=rolled_back_by,
        actor_role="admin",
        action="policy_rollback",
        entity_type="policy",
        entity_id=policy_id,
        detail={"policy_type": policy.policy_type, "rolled_back_from": prev_status},
        ip=None,
    )

    db.session.commit()
    return policy


# ---------------------------------------------------------------------------
# Resolve
# ---------------------------------------------------------------------------

def _find_applicable_rollout(policy_id, segment):
    """
    Find the rollout row that applies to the caller's segment.

    Precedence (highest first):
      1. Segment-specific rollout  (segment == caller's segment, exact match)
      2. Global rollout            (segment IS NULL)

    Returns None when no applicable rollout exists for this policy + segment
    combination, which means the policy should be treated as a full (100%)
    rollout to every user.
    """
    if segment:
        seg_rollout = PolicyRollout.query.filter_by(
            policy_id=policy_id, segment=segment
        ).first()
        if seg_rollout:
            return seg_rollout
    # Global fallback — rollout with no segment restriction
    return (
        PolicyRollout.query
        .filter(
            PolicyRollout.policy_id == policy_id,
            PolicyRollout.segment == None,  # noqa: E711
        )
        .first()
    )


def resolve_policy(policy_type, user_id, segment=None):
    """
    Return rules_json for the effective policy for this user.

    segment:
        Optional caller-supplied segment string (e.g. ``"beta_users"``).
        Used to match against PolicyRollout.segment when choosing which
        canary rows are applicable to this request.

    Rollout precedence:
        Segment-specific rollout > global rollout (segment IS NULL) > no rollout.

    When a matching rollout is found, deterministic hash-bucketing
    (MD5(user_id) % 100 < rollout_pct) decides whether this user is in
    the canary cohort.  Users outside the canary cohort receive the
    non-canary active policy (or the most recent superseded version when
    the canary is the only active version).
    """
    # Find all active policies for this type
    active_policies = (
        Policy.query
        .filter_by(policy_type=policy_type, status="active")
        .all()
    )

    if not active_policies:
        raise LookupError(f"No active policy found for type {policy_type!r}")

    # Identify the canary policy and its applicable rollout for this segment
    canary_policy = None
    canary_rollout_obj = None
    for p in active_policies:
        rollout = _find_applicable_rollout(p.id, segment)
        if rollout:
            canary_policy = p
            canary_rollout_obj = rollout
            break  # first applicable match wins; segment-specific already preferred inside helper

    if canary_policy and canary_rollout_obj:
        # Deterministic bucket assignment
        if is_in_canary(user_id, canary_rollout_obj.rollout_pct):
            return json.loads(canary_policy.rules_json)
        else:
            # User is outside the canary cohort — return the non-canary active policy
            for p in active_policies:
                if p.id != canary_policy.id:
                    return json.loads(p.rules_json)
            # Canary is the only active version; fall back to most recent superseded
            prev = (
                Policy.query
                .filter_by(policy_type=policy_type, status="superseded")
                .order_by(Policy.updated_at.desc())
                .first()
            )
            if prev:
                return json.loads(prev.rules_json)
            # Last resort: return canary rules even to non-canary users
            return json.loads(canary_policy.rules_json)

    # No applicable rollout for this segment → full active policy for everyone
    return json.loads(active_policies[0].rules_json)
