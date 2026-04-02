"""
Master record lifecycle service.
"""
import json
from datetime import datetime, timezone

from app.extensions import db
from app.models.audit import MasterRecord, MasterRecordHistory


def create_master_record(entity_type, entity_id, initial_status, created_by):
    """
    Create a MasterRecord and its first history row in the same transaction.

    :param entity_type:     e.g. "user", "asset"
    :param entity_id:       PK of the entity
    :param initial_status:  Initial status string
    :param created_by:      User ID that triggered creation (None for system)
    :returns:               The new MasterRecord instance
    """
    record = MasterRecord(
        entity_type=entity_type,
        entity_id=entity_id,
        current_status=initial_status,
        created_by=created_by,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.session.add(record)
    db.session.flush()  # assigns record.id

    history = MasterRecordHistory(
        master_record_id=record.id,
        from_status=None,
        to_status=initial_status,
        changed_by=created_by,
        changed_at=datetime.now(timezone.utc),
        snapshot_json=None,
        reason="Initial creation",
    )
    db.session.add(history)
    db.session.flush()

    return record


def transition_master_record(entity_type, entity_id, to_status, changed_by, reason, snapshot=None):
    """
    Append a MasterRecordHistory row and update MasterRecord.current_status.

    :param entity_type: e.g. "user"
    :param entity_id:   PK of the entity
    :param to_status:   New status string
    :param changed_by:  User ID making the change
    :param reason:      Human-readable reason string
    :param snapshot:    Optional dict to serialise as snapshot_json
    :returns:           The updated MasterRecord instance
    """
    record = MasterRecord.query.filter_by(
        entity_type=entity_type,
        entity_id=entity_id,
    ).first()

    if record is None:
        raise ValueError(f"No MasterRecord found for {entity_type}:{entity_id}")

    from_status = record.current_status
    record.current_status = to_status
    record.updated_at = datetime.now(timezone.utc)

    snapshot_json = json.dumps(snapshot) if snapshot is not None else None

    history = MasterRecordHistory(
        master_record_id=record.id,
        from_status=from_status,
        to_status=to_status,
        changed_by=changed_by,
        changed_at=datetime.now(timezone.utc),
        snapshot_json=snapshot_json,
        reason=reason,
    )
    db.session.add(history)
    db.session.flush()

    return record
