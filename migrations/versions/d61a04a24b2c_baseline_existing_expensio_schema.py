
"""Baseline existing Expensio schema

Revision ID: d61a04a24b2c
Revises:
Create Date: 2026-10-25 22:07:18.718661
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d61a04a24b2c"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    with op.batch_alter_table("users") as batch_op:
        batch_op.create_index("ix_users_email", ["email"], unique=True)

    op.create_table(
        "categories",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "id", name="uq_categories_user_id_id"
        ),
        sa.UniqueConstraint(
            "user_id", "name", name="uq_categories_user_name"
        ),
    )

    op.create_table(
        "import_jobs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("s3_object_key", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("total_rows", sa.Integer(), nullable=False),
        sa.Column("imported_rows", sa.Integer(), nullable=False),
        sa.Column("duplicate_rows", sa.Integer(), nullable=False),
        sa.Column("invalid_rows", sa.Integer(), nullable=False),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued', 'processing', 'completed', 'failed')",
            name="ck_import_jobs_status",
        ),
        sa.CheckConstraint(
            "duplicate_rows >= 0",
            name="ck_import_jobs_duplicate_rows_nonnegative",
        ),
        sa.CheckConstraint(
            "imported_rows >= 0",
            name="ck_import_jobs_imported_rows_nonnegative",
        ),
        sa.CheckConstraint(
            "invalid_rows >= 0",
            name="ck_import_jobs_invalid_rows_nonnegative",
        ),
        sa.CheckConstraint(
            "total_rows >= 0",
            name="ck_import_jobs_total_rows_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "id", name="uq_import_jobs_user_id_id"
        ),
    )

    with op.batch_alter_table("import_jobs") as batch_op:
        batch_op.create_index(
            "ix_import_jobs_status", ["status"], unique=False
        )
        batch_op.create_index(
            "ix_import_jobs_user_created",
            ["user_id", "created_at"],
            unique=False,
        )

    op.create_table(
        "budgets",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("category_id", sa.BigInteger(), nullable=True),
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column(
            "amount_limit",
            sa.Numeric(precision=12, scale=2),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "EXTRACT(DAY FROM month) = 1",
            name="ck_budgets_month_first_day",
        ),
        sa.CheckConstraint(
            "amount_limit > 0", name="ck_budgets_amount_positive"
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "category_id"],
            ["categories.user_id", "categories.id"],
            name="fk_budgets_user_category_owner",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    with op.batch_alter_table("budgets") as batch_op:
        batch_op.create_index(
            "uq_budgets_user_month_category",
            ["user_id", "month", "category_id"],
            unique=True,
            postgresql_where=sa.text("category_id IS NOT NULL"),
        )
        batch_op.create_index(
            "uq_budgets_user_month_overall",
            ["user_id", "month"],
            unique=True,
            postgresql_where=sa.text("category_id IS NULL"),
        )

    op.create_table(
        "expenses",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("category_id", sa.BigInteger(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("expense_date", sa.Date(), nullable=False),
        # Legacy column: the next migration removes it.
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("payment_method", sa.String(length=40), nullable=True),
        sa.Column("receipt_object_key", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "source IN ('manual', 'csv')",
            name="ck_expenses_source",
        ),
        sa.CheckConstraint(
            "amount > 0",
            name="ck_expenses_amount_positive",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "category_id"],
            ["categories.user_id", "categories.id"],
            name="fk_expenses_user_category_owner",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "id", name="uq_expenses_user_id_id"
        ),
    )

    with op.batch_alter_table("expenses") as batch_op:
        batch_op.create_index(
            "ix_expenses_user_category",
            ["user_id", "category_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_expenses_user_date",
            ["user_id", "expense_date"],
            unique=False,
        )

    op.create_table(
        "imported_transactions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("import_job_id", sa.BigInteger(), nullable=False),
        sa.Column("expense_id", sa.BigInteger(), nullable=True),
        sa.Column("transaction_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("payment_method", sa.String(length=40), nullable=True),
        sa.Column("deduplication_key", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        # Original FK; the ownership migration replaces this with a composite FK.
        sa.ForeignKeyConstraint(
            ["expense_id"],
            ["expenses.id"],
            name="imported_transactions_expense_id_fkey",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "import_job_id"],
            ["import_jobs.user_id", "import_jobs.id"],
            name="fk_imported_transactions_user_job_owner",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "deduplication_key",
            name="uq_imported_transactions_user_dedupe",
        ),
    )

    with op.batch_alter_table("imported_transactions") as batch_op:
        batch_op.create_index(
            "ix_imported_transactions_job",
            ["import_job_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_imported_transactions_user_date",
            ["user_id", "transaction_date"],
            unique=False,
        )


def downgrade():
    with op.batch_alter_table("imported_transactions") as batch_op:
        batch_op.drop_index("ix_imported_transactions_user_date")
        batch_op.drop_index("ix_imported_transactions_job")
    op.drop_table("imported_transactions")

    with op.batch_alter_table("expenses") as batch_op:
        batch_op.drop_index("ix_expenses_user_date")
        batch_op.drop_index("ix_expenses_user_category")
    op.drop_table("expenses")

    with op.batch_alter_table("budgets") as batch_op:
        batch_op.drop_index(
            "uq_budgets_user_month_overall",
            postgresql_where=sa.text("category_id IS NULL"),
        )
        batch_op.drop_index(
            "uq_budgets_user_month_category",
            postgresql_where=sa.text("category_id IS NOT NULL"),
        )
    op.drop_table("budgets")

    with op.batch_alter_table("import_jobs") as batch_op:
        batch_op.drop_index("ix_import_jobs_user_created")
        batch_op.drop_index("ix_import_jobs_status")
    op.drop_table("import_jobs")

    op.drop_table("categories")

    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_index("ix_users_email")
    op.drop_table("users")
