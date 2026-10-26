
"""Align expenses schema with description contract

Revision ID: 0fd019e3e87b
Revises: d61a04a24b2c
Create Date: 2026-10-26 22:32:58.579348
"""

from alembic import op
import sqlalchemy as sa


# Revision identifiers used by Alembic.
revision = "0fd019e3e87b"
down_revision = "d61a04a24b2c"
branch_labels = None
depends_on = None


def upgrade():
    # Remove the legacy required title column.
    # Existing description values are preserved.
    with op.batch_alter_table("expenses", schema=None) as batch_op:
        batch_op.drop_column("title")


def downgrade():
    # Restore title with a temporary empty-string default so
    # existing rows can satisfy the NOT NULL constraint.
    with op.batch_alter_table("expenses", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "title",
                sa.VARCHAR(length=120),
                nullable=False,
                server_default="",
            )
        )

    # Remove the default after the column has been restored.
    with op.batch_alter_table("expenses", schema=None) as batch_op:
        batch_op.alter_column(
            "title",
            existing_type=sa.VARCHAR(length=120),
            server_default=None,
        )
