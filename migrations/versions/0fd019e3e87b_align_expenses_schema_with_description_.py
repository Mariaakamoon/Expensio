
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
    """Remove the legacy title column from expenses."""
    with op.batch_alter_table("expenses", schema=None) as batch_op:
        batch_op.drop_column("title")


def downgrade():
    """Restore the title column if this migration is rolled back."""
    with op.batch_alter_table("expenses", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "title",
                sa.VARCHAR(length=120),
                nullable=False,
                server_default="",
            )
        )

    # Remove the temporary default after restoring the column.
    with op.batch_alter_table("expenses", schema=None) as batch_op:
        batch_op.alter_column(
            "title",
            existing_type=sa.VARCHAR(length=120),
            server_default=None,
        )
