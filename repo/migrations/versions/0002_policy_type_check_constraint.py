"""Add CHECK constraint on policies.policy_type

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-10 00:00:00.000000

Rationale
---------
policy_type was previously an unconstrained VARCHAR.  This migration adds a
DB-level CHECK constraint so that any direct INSERT or UPDATE that violates
the allowed set is rejected by the database engine itself, providing a second
layer of defence in addition to the service- and schema-level validation.

SQLite note
-----------
SQLite does not support ALTER TABLE ADD CONSTRAINT.  Alembic's
``batch_alter_table`` context manager works around this by copying the table
into a new table with the constraint, then renaming it back.  The operation
is safe when data already satisfies the constraint (all existing rows were
written through the service-layer allowlist).
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ALLOWED = (
    "booking",
    "course_selection",
    "warehouse_ops",
    "pricing",
    "risk",
    "rate_limit",
    "membership",
    "coupon",
)
_CHECK_SQL = "policy_type IN ({})".format(",".join(f"'{t}'" for t in _ALLOWED))


def upgrade() -> None:
    with op.batch_alter_table("policies", schema=None) as batch_op:
        batch_op.create_check_constraint(
            "ck_policies_policy_type",
            _CHECK_SQL,
        )


def downgrade() -> None:
    with op.batch_alter_table("policies", schema=None) as batch_op:
        batch_op.drop_constraint("ck_policies_policy_type", type_="check")
