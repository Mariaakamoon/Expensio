
"""Enforce imported expense ownership.

Revision ID: fc0d238acc48
Revises: 0fd019e3e87b
"""

from alembic import op


revision = "fc0d238acc48"
down_revision = "0fd019e3e87b"
branch_labels = None
depends_on = None


def upgrade():
    # The baseline already creates uq_expenses_user_id_id.
    # Replace the original single-column FK with the composite ownership FK.
    op.drop_constraint(
        "imported_transactions_expense_id_fkey",
        "imported_transactions",
        type_="foreignkey",
    )

    op.create_foreign_key(
        "fk_imported_transactions_user_expense_owner",
        "imported_transactions",
        "expenses",
        ["user_id", "expense_id"],
        ["user_id", "id"],
        ondelete="RESTRICT",
    )


def downgrade():
    op.drop_constraint(
        "fk_imported_transactions_user_expense_owner",
        "imported_transactions",
        type_="foreignkey",
    )

    op.create_foreign_key(
        "imported_transactions_expense_id_fkey",
        "imported_transactions",
        "expenses",
        ["expense_id"],
        ["id"],
        ondelete="SET NULL",
    )
