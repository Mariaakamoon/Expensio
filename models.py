
from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
    text,
)

db = SQLAlchemy()


def utc_now():
    return datetime.now(timezone.utc)


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(254), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now
    )

    categories = db.relationship(
        "Category", back_populates="user", cascade="all, delete-orphan"
    )
    expenses = db.relationship(
        "Expense", back_populates="user", cascade="all, delete-orphan"
    )
    budgets = db.relationship(
        "Budget", back_populates="user", cascade="all, delete-orphan"
    )
    import_jobs = db.relationship(
        "ImportJob", back_populates="user", cascade="all, delete-orphan"
    )
    imported_transactions = db.relationship(
        "ImportedTransaction",
        back_populates="user",
        cascade="all, delete-orphan",
    )


class Category(db.Model):
    __tablename__ = "categories"

    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_categories_user_name"),
        UniqueConstraint("user_id", "id", name="uq_categories_user_id_id"),
    )

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    user_id = db.Column(
        db.BigInteger,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    name = db.Column(db.String(80), nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now
    )

    user = db.relationship("User", back_populates="categories")
    expenses = db.relationship("Expense", back_populates="category")
    budgets = db.relationship("Budget", back_populates="category")


class Expense(db.Model):
    __tablename__ = "expenses"

    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_expenses_amount_positive"),
        CheckConstraint(
            "source IN ('manual', 'csv')", name="ck_expenses_source"
        ),
        ForeignKeyConstraint(
            ["user_id", "category_id"],
            ["categories.user_id", "categories.id"],
            ondelete="RESTRICT",
            name="fk_expenses_user_category_owner",
        ),
        Index("ix_expenses_user_date", "user_id", "expense_date"),
        Index("ix_expenses_user_category", "user_id", "category_id"),
    )

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    user_id = db.Column(
        db.BigInteger,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    category_id = db.Column(db.BigInteger, nullable=False)

    # Kept for the existing dashboard's expense form.
    title = db.Column(db.String(120), nullable=False)

    amount = db.Column(db.Numeric(12, 2), nullable=False)
    expense_date = db.Column(db.Date, nullable=False)
    description = db.Column(db.Text, nullable=True)
    payment_method = db.Column(db.String(40), nullable=True)
    receipt_object_key = db.Column(db.Text, nullable=True)
    source = db.Column(db.String(10), nullable=False, default="manual")
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    user = db.relationship("User", back_populates="expenses")
    category = db.relationship("Category", back_populates="expenses")
    imported_transactions = db.relationship(
        "ImportedTransaction", back_populates="expense"
    )


class Budget(db.Model):
    __tablename__ = "budgets"

    __table_args__ = (
        CheckConstraint(
            "amount_limit > 0", name="ck_budgets_amount_positive"
        ),
        CheckConstraint(
            "EXTRACT(DAY FROM month) = 1",
            name="ck_budgets_month_first_day",
        ),
        ForeignKeyConstraint(
            ["user_id", "category_id"],
            ["categories.user_id", "categories.id"],
            ondelete="RESTRICT",
            name="fk_budgets_user_category_owner",
        ),
        Index(
            "uq_budgets_user_month_overall",
            "user_id",
            "month",
            unique=True,
            postgresql_where=text("category_id IS NULL"),
        ),
        Index(
            "uq_budgets_user_month_category",
            "user_id",
            "month",
            "category_id",
            unique=True,
            postgresql_where=text("category_id IS NOT NULL"),
        ),
    )

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    user_id = db.Column(
        db.BigInteger,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    category_id = db.Column(db.BigInteger, nullable=True)
    month = db.Column(db.Date, nullable=False)
    amount_limit = db.Column(db.Numeric(12, 2), nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    user = db.relationship("User", back_populates="budgets")
    category = db.relationship("Category", back_populates="budgets")


class ImportJob(db.Model):
    __tablename__ = "import_jobs"

    __table_args__ = (
        UniqueConstraint("user_id", "id", name="uq_import_jobs_user_id_id"),
        CheckConstraint(
            "status IN ('queued', 'processing', 'completed', 'failed')",
            name="ck_import_jobs_status",
        ),
        CheckConstraint(
            "total_rows >= 0",
            name="ck_import_jobs_total_rows_nonnegative",
        ),
        CheckConstraint(
            "imported_rows >= 0",
            name="ck_import_jobs_imported_rows_nonnegative",
        ),
        CheckConstraint(
            "duplicate_rows >= 0",
            name="ck_import_jobs_duplicate_rows_nonnegative",
        ),
        CheckConstraint(
            "invalid_rows >= 0",
            name="ck_import_jobs_invalid_rows_nonnegative",
        ),
        Index("ix_import_jobs_user_created", "user_id", "created_at"),
        Index("ix_import_jobs_status", "status"),
    )

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    user_id = db.Column(
        db.BigInteger,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    s3_object_key = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="queued")
    total_rows = db.Column(db.Integer, nullable=False, default=0)
    imported_rows = db.Column(db.Integer, nullable=False, default=0)
    duplicate_rows = db.Column(db.Integer, nullable=False, default=0)
    invalid_rows = db.Column(db.Integer, nullable=False, default=0)
    error_summary = db.Column(db.Text, nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    user = db.relationship("User", back_populates="import_jobs")
    imported_transactions = db.relationship(
        "ImportedTransaction",
        back_populates="import_job",
        cascade="all, delete-orphan",
    )


class ImportedTransaction(db.Model):
    __tablename__ = "imported_transactions"

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "deduplication_key",
            name="uq_imported_transactions_user_dedupe",
        ),
        Index(
            "ix_imported_transactions_user_date",
            "user_id",
            "transaction_date",
        ),
        Index("ix_imported_transactions_job", "import_job_id"),
        ForeignKeyConstraint(
            ["user_id", "import_job_id"],
            ["import_jobs.user_id", "import_jobs.id"],
            ondelete="CASCADE",
            name="fk_imported_transactions_user_job_owner",
        ),
    )

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    user_id = db.Column(
        db.BigInteger,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    import_job_id = db.Column(db.BigInteger, nullable=False)
    expense_id = db.Column(
        db.BigInteger,
        db.ForeignKey("expenses.id", ondelete="SET NULL"),
        nullable=True,
    )
    transaction_date = db.Column(db.Date, nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    description = db.Column(db.Text, nullable=True)
    payment_method = db.Column(db.String(40), nullable=True)
    deduplication_key = db.Column(db.String(64), nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now
    )

    user = db.relationship("User", back_populates="imported_transactions")
    import_job = db.relationship(
        "ImportJob", back_populates="imported_transactions"
    )
    expense = db.relationship(
        "Expense", back_populates="imported_transactions"
    )
