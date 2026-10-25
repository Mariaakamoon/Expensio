
import os
from datetime import date
from decimal import Decimal, InvalidOperation

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from models import db, User, Category, Expense

load_dotenv()

app = Flask(__name__)

database_url = os.getenv("DATABASE_URL")
if not database_url:
    raise RuntimeError(
        "DATABASE_URL is missing. Create a local .env file."
    )

app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db.init_app(app)

# Temporary identity for local development only.
# Replace this with real authentication before production deployment.
DEV_EMAIL = "local-dev@expensio.invalid"

DEFAULT_CATEGORIES = [
    "Food",
    "Transport",
    "Shopping",
    "Bills",
    "Health",
    "Other",
]


def get_dev_user():
    user = db.session.execute(
        select(User).where(User.email == DEV_EMAIL)
    ).scalar_one_or_none()

    if user is None:
        user = User(
            name="Local Development User",
            email=DEV_EMAIL,
            password_hash="NOT_FOR_AUTHENTICATION",
        )
        db.session.add(user)
        db.session.flush()

    existing_categories = set(
        db.session.execute(
            select(Category.name).where(Category.user_id == user.id)
        ).scalars().all()
    )
    existing_lower = {name.lower() for name in existing_categories}

    for name in DEFAULT_CATEGORIES:
        if name.lower() not in existing_lower:
            db.session.add(Category(user_id=user.id, name=name))

    db.session.commit()
    return user


def expense_to_dict(expense):
    return {
        "id": expense.id,
        "title": expense.title,
        "amount": str(expense.amount),
        "category": expense.category.name,
        "expense_date": expense.expense_date.isoformat(),
        "description": expense.description,
        "created_at": (
            expense.created_at.isoformat()
            if expense.created_at
            else None
        ),
        "receipts": (
            [
                {
                    "id": None,
                    "original_filename": "Receipt stored in S3",
                    "s3_key": expense.receipt_object_key,
                }
            ]
            if expense.receipt_object_key
            else []
        ),
    }


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/health")
def health():
    try:
        db.session.execute(select(1))
        return jsonify({
            "status": "ok",
            "application": "Expensio",
            "database": "connected",
        }), 200
    except SQLAlchemyError:
        db.session.rollback()
        app.logger.exception("Health check database failure")
        return jsonify({
            "status": "error",
            "database": "unavailable",
        }), 503


@app.route("/api/expenses", methods=["GET", "POST"])
def expenses():
    try:
        user = get_dev_user()

        if request.method == "GET":
            items = db.session.execute(
                select(Expense)
                .where(Expense.user_id == user.id)
                .order_by(
                    Expense.expense_date.desc(),
                    Expense.id.desc(),
                )
            ).scalars().all()

            return jsonify([expense_to_dict(item) for item in items]), 200

        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"error": "Send a valid JSON object."}), 400

        title = data.get("title")
        category_name = data.get("category")
        raw_amount = data.get("amount")
        raw_date = data.get("expense_date")
        description = data.get("description")

        if not all(
            isinstance(value, str) and value.strip()
            for value in (title, category_name, raw_date)
        ):
            return jsonify({
                "error": "Title, category and expense_date are required."
            }), 400

        title = title.strip()
        category_name = category_name.strip()

        if len(title) > 120 or len(category_name) > 80:
            return jsonify({"error": "Title or category is too long."}), 400

        if description is not None and not isinstance(description, str):
            return jsonify({"error": "Description must be text."}), 400

        try:
            amount = Decimal(str(raw_amount))
            if (
                not amount.is_finite()
                or amount <= 0
                or amount.as_tuple().exponent < -2
            ):
                raise InvalidOperation
        except (InvalidOperation, ValueError, TypeError):
            return jsonify({
                "error": "Amount must be positive and have at most 2 decimal places."
            }), 400

        try:
            parsed_date = date.fromisoformat(raw_date)
        except ValueError:
            return jsonify({
                "error": "expense_date must use YYYY-MM-DD format."
            }), 400

        category = db.session.execute(
            select(Category).where(
                Category.user_id == user.id,
                db.func.lower(Category.name) == category_name.lower(),
            )
        ).scalar_one_or_none()

        if category is None:
            category = Category(user_id=user.id, name=category_name)
            db.session.add(category)
            db.session.flush()

        expense = Expense(
            user_id=user.id,
            category_id=category.id,
            title=title,
            amount=amount,
            expense_date=parsed_date,
            description=(
                description.strip()
                if description and description.strip()
                else None
            ),
            source="manual",
        )

        db.session.add(expense)
        db.session.commit()

        return jsonify(expense_to_dict(expense)), 201

    except SQLAlchemyError:
        db.session.rollback()
        app.logger.exception("Database error in expenses endpoint")
        return jsonify({
            "error": "Database operation failed. Check the terminal logs."
        }), 500


@app.route(
    "/api/expenses/<int:expense_id>",
    methods=["GET", "PUT", "PATCH", "DELETE"],
)
def expense_detail(expense_id):
    try:
        user = get_dev_user()

        expense = db.session.execute(
            select(Expense).where(
                Expense.id == expense_id,
                Expense.user_id == user.id,
            )
        ).scalar_one_or_none()

        if expense is None:
            return jsonify({"error": "Expense not found."}), 404

        if request.method == "GET":
            return jsonify(expense_to_dict(expense)), 200

        if request.method == "DELETE":
            db.session.delete(expense)
            db.session.commit()
            return "", 204

        data = request.get_json(silent=True)
        allowed_fields = {
            "title",
            "amount",
            "category",
            "expense_date",
            "description",
        }

        if (
            not isinstance(data, dict)
            or not data
            or not set(data).issubset(allowed_fields)
        ):
            return jsonify({"error": "Provide valid expense fields."}), 400

        if "title" in data:
            title = data["title"]
            if (
                not isinstance(title, str)
                or not title.strip()
                or len(title.strip()) > 120
            ):
                return jsonify({
                    "error": "Title must be 1–120 characters."
                }), 400
            expense.title = title.strip()

        if "category" in data:
            category_name = data["category"]
            if (
                not isinstance(category_name, str)
                or not category_name.strip()
                or len(category_name.strip()) > 80
            ):
                return jsonify({
                    "error": "Category must be 1–80 characters."
                }), 400

            category = db.session.execute(
                select(Category).where(
                    Category.user_id == user.id,
                    db.func.lower(Category.name)
                    == category_name.strip().lower(),
                )
            ).scalar_one_or_none()

            if category is None:
                category = Category(
                    user_id=user.id,
                    name=category_name.strip(),
                )
                db.session.add(category)
                db.session.flush()

            expense.category_id = category.id

        if "amount" in data:
            try:
                amount = Decimal(str(data["amount"]))
                if (
                    not amount.is_finite()
                    or amount <= 0
                    or amount.as_tuple().exponent < -2
                ):
                    raise InvalidOperation
                expense.amount = amount
            except (InvalidOperation, ValueError, TypeError):
                return jsonify({
                    "error": "Amount must be positive and have at most 2 decimal places."
                }), 400

        if "expense_date" in data:
            try:
                if not isinstance(data["expense_date"], str):
                    raise ValueError
                expense.expense_date = date.fromisoformat(
                    data["expense_date"]
                )
            except ValueError:
                return jsonify({
                    "error": "expense_date must use YYYY-MM-DD format."
                }), 400

        if "description" in data:
            description = data["description"]
            if description is not None and not isinstance(description, str):
                return jsonify({
                    "error": "Description must be text."
                }), 400
            expense.description = (
                description.strip() if description else None
            )

        db.session.commit()
        return jsonify(expense_to_dict(expense)), 200

    except SQLAlchemyError:
        db.session.rollback()
        app.logger.exception("Database error in expense detail endpoint")
        return jsonify({
            "error": "Database operation failed. Check the terminal logs."
        }), 500


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        get_dev_user()

    app.run(
        host="127.0.0.1",
        port=5001,
        debug=os.getenv("FLASK_DEBUG", "0") == "1",
    )
