
from datetime import date
from decimal import Decimal, InvalidOperation

from flask import Flask, jsonify, render_template, request

from models import db, Expense, Receipt

app = Flask(__name__)

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///expensio.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)


def expense_to_dict(expense):
    return {
        "id": expense.id,
        "title": expense.title,
        "amount": str(expense.amount),
        "category": expense.category,
        "expense_date": expense.expense_date.isoformat(),
        "description": expense.description,
        "created_at": (
            expense.created_at.isoformat()
            if expense.created_at else None
        ),
        "receipts": [
            {
                "id": receipt.id,
                "original_filename": receipt.original_filename,
                "s3_key": receipt.s3_key,
            }
            for receipt in expense.receipts
        ],
    }


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/health")
def health():
    return {"status": "ok", "application": "Expensio"}, 200


@app.route("/api/expenses", methods=["GET", "POST"])
def expenses():
    if request.method == "GET":
        all_expenses = Expense.query.order_by(
            Expense.expense_date.desc()
        ).all()
        return jsonify([expense_to_dict(e) for e in all_expenses]), 200

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Send a valid JSON object."}), 400

    title = data.get("title")
    category = data.get("category")
    amount = data.get("amount")
    expense_date = data.get("expense_date")
    description = data.get("description")

    if not all(isinstance(v, str) and v.strip()
               for v in [title, category, expense_date]):
        return jsonify({
            "error": "Title, category and expense_date are required."
        }), 400

    if len(title.strip()) > 120 or len(category.strip()) > 80:
        return jsonify({"error": "Title or category is too long."}), 400

    try:
        amount = Decimal(str(amount))
        if not amount.is_finite() or amount <= 0 or amount.as_tuple().exponent < -2:
            raise InvalidOperation
    except (InvalidOperation, ValueError, TypeError):
        return jsonify({
            "error": "Amount must be positive and have at most 2 decimal places."
        }), 400

    try:
        parsed_date = date.fromisoformat(expense_date)
    except ValueError:
        return jsonify({
            "error": "expense_date must use YYYY-MM-DD format."
        }), 400

    if description is not None and not isinstance(description, str):
        return jsonify({"error": "Description must be text."}), 400

    expense = Expense(
        title=title.strip(),
        amount=amount,
        category=category.strip(),
        expense_date=parsed_date,
        description=description.strip() if description else None,
    )

    db.session.add(expense)
    db.session.commit()

    return jsonify(expense_to_dict(expense)), 201


@app.route("/api/expenses/<int:expense_id>", methods=["GET", "PUT", "PATCH", "DELETE"])
def expense_detail(expense_id):
    expense = db.session.get(Expense, expense_id)

    if expense is None:
        return jsonify({"error": "Expense not found."}), 404

    if request.method == "GET":
        return jsonify(expense_to_dict(expense)), 200

    if request.method == "DELETE":
        db.session.delete(expense)
        db.session.commit()
        return "", 204

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Send a valid JSON object."}), 400

    allowed_fields = {
        "title", "amount", "category", "expense_date", "description"
    }
    if not data or not set(data).issubset(allowed_fields):
        return jsonify({"error": "Provide valid expense fields."}), 400

    if "title" in data:
        if not isinstance(data["title"], str) or not data["title"].strip():
            return jsonify({"error": "Title cannot be empty."}), 400
        if len(data["title"].strip()) > 120:
            return jsonify({"error": "Title is too long."}), 400
        expense.title = data["title"].strip()

    if "category" in data:
        if not isinstance(data["category"], str) or not data["category"].strip():
            return jsonify({"error": "Category cannot be empty."}), 400
        if len(data["category"].strip()) > 80:
            return jsonify({"error": "Category is too long."}), 400
        expense.category = data["category"].strip()

    if "amount" in data:
        try:
            amount = Decimal(str(data["amount"]))
            if not amount.is_finite() or amount <= 0 or amount.as_tuple().exponent < -2:
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
            expense.expense_date = date.fromisoformat(data["expense_date"])
        except ValueError:
            return jsonify({
                "error": "expense_date must use YYYY-MM-DD format."
            }), 400

    if "description" in data:
        if data["description"] is not None and not isinstance(data["description"], str):
            return jsonify({"error": "Description must be text."}), 400
        expense.description = (
            data["description"].strip() if data["description"] else None
        )

    db.session.commit()
    return jsonify(expense_to_dict(expense)), 200


if __name__ == "__main__":
    with app.app_context():
        db.create_all()

    app.run(port=5001, debug=True)
