
"""Enforce imported expense ownership.

Revision ID: fc0d238acc48
Revises: 0fd019e3e87b
"""

from alembic import op
import sqlalchemy as sa


revision = "fc0d238acc48"
down_revision = "0fd019e3e87b"
branch_labels = None
depends_on = None


def _foreign_keys(table_name):
    return sa.inspect(op.get_bind()).get_foreign_keys(table_name)


def _has_expense_owner_fk():
    return any(
        fk.get("constrained_columns") == ["user_id", "expense_id"]
        and fk.get("referred_table") == "expenses"
        and fk.get("referred_columns") == ["user_id", "id"]
        for fk in _foreign_keys("imported_transactions")
    )


def _has_simple_expense_fk():
    return any(
        fk.get("constrained_columns") == ["expense_id"]
        and fk.get("referred_table") == "expenses"
        and fk.get("referred_columns") == ["id"]
        for fk in _foreign_keys("imported_transactions")
    )


def _has_expenses_unique_pair():
    inspector = sa.inspect(op.get_bind())
    columns = ["user_id", "id"]

    if any(
        set(item.get("column_names") or []) == set(columns)
        for item in inspector.get_unique_constraints("expenses")
    ):
        return True

    return any(
        item.get("unique")
        and set(item.get("column_names") or []) == set(columns)
        for item in inspector.get_indexes("expenses")
    )


def upgrade():
    # Add the referenced unique key only if it does not already exist.
    if not _has_expenses_unique_pair():
        op.create_unique_constraint(
            "uq_expenses_user_id_id",
            "expenses",
            ["user_id", "id"],
        )

    # Remove the old single-column FK if this database still has it.
    if not _has_expense_owner_fk():
        for fk in _foreign_keys("imported_transactions"):
            if (
                fk.get("constrained_columns") == ["expense_id"]
                and fk.get("referred_table") == "expenses"
                and fk.get("referred_columns") == ["id"]
            ):
                op.drop_constraint(
                    fk["name"],
                    "imported_transactions",
                    type_="foreignkey",
                )

        # Add the composite FK only if it is not already present.
        if not _has_expense_owner_fk():
            op.create_foreign_key(
                "fk_imported_transactions_user_expense_owner",
                "imported_transactions",
                "expenses",
                ["user_id", "expense_id"],
                ["user_id", "id"],
                ondelete="RESTRICT",
            )


def downgrade():
    # Restore the old single-column FK without duplicating constraints.
    if _has_expense_owner_fk():
        for fk in _foreign_keys("imported_transactions"):
            if (
                fk.get("constrained_columns") == ["user_id", "expense_id"]
                and fk.get("referred_table") == "expenses"
                and fk.get("referred_columns") == ["user_id", "id"]
            ):
                op.drop_constraint(
                    fk["name"],
                    "imported_transactions",
                    type_="foreignkey",
                )

    if not _has_simple_expense_fk():
        op.create_foreign_key(
            "imported_transactions_expense_id_fkey",
            "imported_transactions",
            "expenses",
            ["expense_id"],
            ["id"],
            ondelete="SET NULL",
        )

    # Keep uq_expenses_user_id_id: it is also part of the baseline schema.
