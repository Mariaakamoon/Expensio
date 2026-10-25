
import os
import logging
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import PurePosixPath
from flask_migrate import Migrate

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from werkzeug.utils import secure_filename
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

AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")
S3_RECEIPTS_BUCKET = os.getenv("S3_RECEIPTS_BUCKET")

# Receipt upload limits and permitted file extensions.
MAX_RECEIPT_SIZE = 5 * 1024 * 1024  # 5 MiB
ALLOWED_RECEIPT_EXTENSIONS = {"jpg", "jpeg", "png", "pdf"}

app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = MAX_RECEIPT_SIZE + (64 * 1024)

db.init_app(app)
migrate = Migrate(app, db)
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

ALLOWED_RECEIPT_MIME_TYPES = {
    "jpg": {"image/jpeg"},
    "jpeg": {"image/jpeg"},
    "png": {"image/png"},
    "pdf": {"application/pdf"},
}


def get_s3_client():
    """Use the standard AWS credential chain, not hard-coded keys."""
    return boto3.client("s3", region_name=AWS_REGION)


def receipt_storage_configured():
    return bool(S3_RECEIPTS_BUCKET)


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
    receipt_filename = None

    if expense.receipt_object_key:
        stored_name = PurePosixPath(
            expense.receipt_object_key
        ).name
        # The key includes a random prefix to avoid collisions.
        receipt_filename = stored_name.split("_", 1)[-1]

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
                    "original_filename": receipt_filename,
                    "s3_key": expense.receipt_object_key,
                }
            ]
            if expense.receipt_object_key
            else []
        ),
    }


def find_user_expense(expense_id, user_id):
    return db.session.execute(
        select(Expense).where(
            Expense.id == expense_id,
            Expense.user_id == user_id,
        )
    ).scalar_one_or_none()


def s3_error_response(error, action):
    app.logger.error(
        "S3 %s failed: %s",
        action,
        error,
        exc_info=True,
    )
    return jsonify({
        "error": (
            f"Receipt {action} failed. Check the application logs "
            "and AWS permissions."
        )
    }), 502


@app.errorhandler(413)
def request_entity_too_large(_error):
    return jsonify({
        "error": "Receipt upload is too large. Maximum file size is 5 MB."
    }), 413


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
            query = select(Expense).where(
                Expense.user_id == user.id
            )

            category_name = request.args.get("category", "").strip()
            start_date = request.args.get("start_date", "").strip()
            end_date = request.args.get("end_date", "").strip()

            if category_name:
                query = query.join(Expense.category).where(
                    db.func.lower(Category.name)
                    == category_name.lower()
                )

            if start_date:
                try:
                    parsed_start = date.fromisoformat(start_date)
                except ValueError:
                    return jsonify({
                        "error": "start_date must use YYYY-MM-DD format."
                    }), 400

                query = query.where(
                    Expense.expense_date >= parsed_start
                )

            if end_date:
                try:
                    parsed_end = date.fromisoformat(end_date)
                except ValueError:
                    return jsonify({
                        "error": "end_date must use YYYY-MM-DD format."
                    }), 400

                query = query.where(
                    Expense.expense_date <= parsed_end
                )

            if start_date and end_date and parsed_start > parsed_end:
                return jsonify({
                    "error": "start_date cannot be after end_date."
                }), 400

            items = db.session.execute(
                query.order_by(
                    Expense.expense_date.desc(),
                    Expense.id.desc(),
                )
            ).scalars().all()

            return jsonify([
                expense_to_dict(item) for item in items
            ]), 200

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
                "error": (
                    "Amount must be positive and have at most "
                    "2 decimal places."
                )
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
        expense = find_user_expense(expense_id, user.id)

        if expense is None:
            return jsonify({"error": "Expense not found."}), 404

        if request.method == "GET":
            return jsonify(expense_to_dict(expense)), 200

        if request.method == "DELETE":
            # Remove the receipt first so a failed S3 deletion does not
            # silently leave a referenced object behind.
            if expense.receipt_object_key:
                if not receipt_storage_configured():
                    return jsonify({
                        "error": "Receipt storage is not configured."
                    }), 503
                try:
                    get_s3_client().delete_object(
                        Bucket=S3_RECEIPTS_BUCKET,
                        Key=expense.receipt_object_key,
                    )
                except (BotoCoreError, ClientError):
                    app.logger.exception(
                        "Could not delete receipt before expense deletion"
                    )
                    return jsonify({
                        "error": "Could not delete the receipt. Expense was not deleted."
                    }), 502

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
                    "error": "Title must be 1-120 characters."
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
                    "error": "Category must be 1-80 characters."
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
                    "error": (
                        "Amount must be positive and have at most "
                        "2 decimal places."
                    )
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


@app.route(
    "/api/expenses/<int:expense_id>/receipt",
    methods=["POST"],
)
def upload_receipt(expense_id):
    if not receipt_storage_configured():
        return jsonify({
            "error": "Receipt storage is not configured."
        }), 503

    uploaded_file = request.files.get("receipt")
    if uploaded_file is None or not uploaded_file.filename:
        return jsonify({
            "error": "Choose a receipt file using the 'receipt' field."
        }), 400

    safe_filename = secure_filename(uploaded_file.filename)
    if not safe_filename or "." not in safe_filename:
        return jsonify({"error": "Invalid filename."}), 400

    extension = safe_filename.rsplit(".", 1)[1].lower()
    if extension not in ALLOWED_RECEIPT_EXTENSIONS:
        return jsonify({
            "error": "Only JPG, JPEG, PNG, and PDF receipts are allowed."
        }), 415

    content_type = (uploaded_file.mimetype or "").lower()
    if content_type not in ALLOWED_RECEIPT_MIME_TYPES[extension]:
        return jsonify({
            "error": "The file type does not match the filename extension."
        }), 415

    try:
        user = get_dev_user()
        expense = find_user_expense(expense_id, user.id)

        if expense is None:
            return jsonify({"error": "Expense not found."}), 404

        # Read at most one byte beyond the limit to enforce the size cap.
        file_data = uploaded_file.stream.read(MAX_RECEIPT_SIZE + 1)
        if not file_data:
            return jsonify({"error": "The receipt file is empty."}), 400
        if len(file_data) > MAX_RECEIPT_SIZE:
            return jsonify({
                "error": "Receipt file exceeds the 5 MB limit."
            }), 413

        object_key = (
            f"receipts/{user.id}/{expense.id}/"
            f"{uuid.uuid4().hex}_{safe_filename}"
        )
        old_key = expense.receipt_object_key

        try:
            get_s3_client().put_object(
                Bucket=S3_RECEIPTS_BUCKET,
                Key=object_key,
                Body=file_data,
                ContentType=content_type,
                ServerSideEncryption="AES256",
            )
        except (BotoCoreError, ClientError) as error:
            return s3_error_response(error, "upload")

        expense.receipt_object_key = object_key
        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            app.logger.exception(
                "Database save failed after receipt upload; cleaning up S3 object"
            )
            try:
                get_s3_client().delete_object(
                    Bucket=S3_RECEIPTS_BUCKET,
                    Key=object_key,
                )
            except (BotoCoreError, ClientError):
                app.logger.exception(
                    "Could not clean up unreferenced uploaded receipt"
                )
            return jsonify({
                "error": "Could not save the receipt reference to the database."
            }), 500

        # If replacing an old receipt, remove it after the new reference is saved.
        if old_key and old_key != object_key:
            try:
                get_s3_client().delete_object(
                    Bucket=S3_RECEIPTS_BUCKET,
                    Key=old_key,
                )
            except (BotoCoreError, ClientError):
                app.logger.exception(
                    "New receipt saved, but the previous S3 object could not be deleted"
                )

        return jsonify({
            "message": "Receipt uploaded successfully.",
            "expense_id": expense.id,
            "original_filename": safe_filename,
            "s3_key": object_key,
        }), 201

    except SQLAlchemyError:
        db.session.rollback()
        app.logger.exception("Database error during receipt upload")
        return jsonify({
            "error": "Database operation failed. Check the terminal logs."
        }), 500


@app.route(
    "/api/expenses/<int:expense_id>/receipt",
    methods=["GET"],
)
def download_receipt(expense_id):
    if not receipt_storage_configured():
        return jsonify({
            "error": "Receipt storage is not configured."
        }), 503

    try:
        user = get_dev_user()
        expense = find_user_expense(expense_id, user.id)

        if expense is None:
            return jsonify({"error": "Expense not found."}), 404

        if not expense.receipt_object_key:
            return jsonify({"error": "This expense has no receipt."}), 404

        try:
            # URL expires after five minutes. The bucket remains private.
            url = get_s3_client().generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": S3_RECEIPTS_BUCKET,
                    "Key": expense.receipt_object_key,
                },
                ExpiresIn=300,
            )
        except (BotoCoreError, ClientError) as error:
            return s3_error_response(error, "download URL generation")

        return jsonify({
            "download_url": url,
            "expires_in_seconds": 300,
        }), 200

    except SQLAlchemyError:
        db.session.rollback()
        app.logger.exception("Database error during receipt download")
        return jsonify({
            "error": "Database operation failed. Check the terminal logs."
        }), 500


@app.route(
    "/api/expenses/<int:expense_id>/receipt",
    methods=["DELETE"],
)
def delete_receipt(expense_id):
    if not receipt_storage_configured():
        return jsonify({
            "error": "Receipt storage is not configured."
        }), 503

    try:
        user = get_dev_user()
        expense = find_user_expense(expense_id, user.id)

        if expense is None:
            return jsonify({"error": "Expense not found."}), 404

        if not expense.receipt_object_key:
            return jsonify({"error": "This expense has no receipt."}), 404

        object_key = expense.receipt_object_key

        try:
            get_s3_client().delete_object(
                Bucket=S3_RECEIPTS_BUCKET,
                Key=object_key,
            )
        except (BotoCoreError, ClientError) as error:
            return s3_error_response(error, "deletion")

        expense.receipt_object_key = None
        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            app.logger.exception(
                "S3 receipt deleted, but database reference could not be cleared"
            )
            return jsonify({
                "error": (
                    "Receipt was deleted from S3, but the database update failed. "
                    "Retry or check the expense record."
                )
            }), 500

        return jsonify({"message": "Receipt deleted successfully."}), 200

    except SQLAlchemyError:
        db.session.rollback()
        app.logger.exception("Database error during receipt deletion")
        return jsonify({
            "error": "Database operation failed. Check the terminal logs."
        }), 500


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    with app.app_context():
        db.create_all()
        get_dev_user()

    app.run(
        host="127.0.0.1",
        port=5001,
        debug=os.getenv("FLASK_DEBUG", "0") == "1",
    )
