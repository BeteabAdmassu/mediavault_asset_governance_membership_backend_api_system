"""
Audit logging service.
"""
import json
from datetime import datetime, timezone

from app.extensions import db
from app.models.audit import AuditLog


def log_audit(actor_id, actor_role, action, entity_type, entity_id, detail, ip):
    """
    Create an AuditLog row.

    :param actor_id:    User ID performing the action (None for anonymous)
    :param actor_role:  Role string of the actor (None for anonymous)
    :param action:      Action string, e.g. "login_success"
    :param entity_type: Target entity type, e.g. "user"
    :param entity_id:   Target entity PK
    :param detail:      Dict or string with additional context
    :param ip:          Client IP address
    """
    if isinstance(detail, dict):
        detail_json = json.dumps(detail)
    elif detail is not None:
        detail_json = str(detail)
    else:
        detail_json = None

    entry = AuditLog(
        actor_id=actor_id,
        actor_role=actor_role,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        detail_json=detail_json,
        ip=ip,
        created_at=datetime.now(timezone.utc),
    )
    db.session.add(entry)
    # Flush so the row gets an ID, but let the caller commit.
    db.session.flush()
