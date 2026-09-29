"""Adopt runtime-added users / performance_periods columns into Alembic.

Revision ID: w1c5a7d2e9b4
Revises: v1a2d3e4f5b6
Create Date: 2026-09-28

The ORM maps these columns, but no migration created them; they were added at
runtime (users: app/services/cic celebration code; performance_periods: the
startup schema guard patch list). Production already has them (verified
2026-09-28, and every ORM query on User / PerformancePeriod depends on them),
while a database built only with ``flask db upgrade`` did not.

Adoption rules: a column is added only when it is absent, with the ORM type;
existing columns and data are never touched, so this is a no-op on production.
The ORM also declares indexes on some of these columns; their presence in
production is unverified, so they are intentionally not created here.

Downgrade keeps the columns (they hold institutional data and predate this
revision).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "w1c5a7d2e9b4"
down_revision = "v1a2d3e4f5b6"
branch_labels = None
depends_on = None

def adopted_columns() -> dict[str, tuple[sa.Column, ...]]:
    return {
        "users": (
            sa.Column("birth_date", sa.Date(), nullable=True),
            sa.Column("hire_date", sa.Date(), nullable=True),
            sa.Column("celebration_opt_out", sa.Boolean(), nullable=False, server_default=sa.false()),
        ),
        "performance_periods": (
            sa.Column("evaluation_start_date", sa.Date(), nullable=True),
            sa.Column("evaluation_end_date", sa.Date(), nullable=True),
            sa.Column("evaluation_due_days", sa.Integer(), nullable=True),
        ),
    }


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table, columns in adopted_columns().items():
        if not inspector.has_table(table):
            continue
        existing = {column["name"] for column in inspector.get_columns(table)}
        for column in columns:
            if column.name not in existing:
                op.add_column(table, column)


def downgrade() -> None:
    """Keep the adopted columns; they predate this revision."""
