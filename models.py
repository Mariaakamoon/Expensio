
from datetime import datetime

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    category = db.Column(db.String(80), nullable=False)
    expense_date = db.Column(db.Date, nullable=False)
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    receipts = db.relationship(
        "Receipt",
        backref="expense",
        cascade="all, delete-orphan",
        lazy=True,
    )


class Receipt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    expense_id = db.Column(
        db.Integer,
        db.ForeignKey("expense.id"),
        nullable=False,
    )
    original_filename = db.Column(db.String(255), nullable=False)
    s3_key = db.Column(db.String(500), nullable=True)
    content_type = db.Column(db.String(100), nullable=True)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
