
import csv
import hashlib
import io
import re
from datetime import date
from decimal import Decimal, InvalidOperation


REQUIRED_HEADERS = {
    "transaction_date",
    "amount",
    "description",
    "payment_method",
    "category",
}

MAX_AMOUNT = Decimal("9999999999.99")
AMOUNT_PATTERN = re.compile(r"^-?\d+(?:\.\d{1,2})?$")


def make_deduplication_key(
    transaction_date,
    amount,
    description,
    payment_method,
    category,
):
    """Create a stable SHA-256 key for a normalized transaction."""
    normalized = "|".join(
        [
            transaction_date.isoformat(),
            format(amount, ".2f"),
            description.strip(),
            payment_method.strip().casefold(),
            category.strip().casefold(),
        ]
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def validate_csv(csv_content):
    """
    Validate CSV text and return:
      {
        "valid_transactions": [...],
        "credits": [...],
        "errors": [...]
      }

    Negative amounts are expenses. Positive amounts are credits/refunds.
    Invalid rows are reported without stopping the entire import.
    """
    result = {
        "valid_transactions": [],
        "credits": [],
        "errors": [],
    }

    try:
        reader = csv.DictReader(io.StringIO(csv_content.lstrip("\ufeff")))
        if not reader.fieldnames:
            result["errors"].append(
                {"row": 1, "error": "CSV file is empty or has no header."}
            )
            return result

        # Normalize headers: trim whitespace and ignore capitalization.
        normalized_headers = [
            header.strip().casefold() if header else ""
            for header in reader.fieldnames
        ]

        if len(normalized_headers) != len(set(normalized_headers)):
            result["errors"].append(
                {"row": 1, "error": "CSV contains duplicate column headers."}
            )
            return result

        missing_headers = REQUIRED_HEADERS - set(normalized_headers)
        if missing_headers:
            result["errors"].append(
                {
                    "row": 1,
                    "error": "Missing required headers: "
                    + ", ".join(sorted(missing_headers)),
                }
            )
            return result

        reader.fieldnames = normalized_headers

        for row_number, row in enumerate(reader, start=2):
            try:
                if None in row:
                    raise ValueError("Row contains more values than the header.")

                if any(value is None for value in row.values()):
                    raise ValueError("Row has missing values.")

                transaction_date_text = row["transaction_date"].strip()
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", transaction_date_text):
                    raise ValueError("Date must use YYYY-MM-DD format.")

                transaction_date = date.fromisoformat(transaction_date_text)

                amount_text = row["amount"].strip()
                if not AMOUNT_PATTERN.fullmatch(amount_text):
                    raise ValueError(
                        "Amount must be numeric with at most two decimal places."
                    )

                try:
                    amount = Decimal(amount_text)
                except InvalidOperation:
                    raise ValueError("Amount is not a valid number.")

                if amount == 0:
                    raise ValueError("Amount cannot be zero.")

                if abs(amount) > MAX_AMOUNT:
                    raise ValueError("Amount exceeds the supported limit.")

                description = row["description"].strip()
                payment_method = row["payment_method"].strip()
                category = row["category"].strip()

                if not description:
                    raise ValueError("Description cannot be empty.")

                if not payment_method:
                    raise ValueError("Payment method cannot be empty.")

                if not category:
                    raise ValueError("Category cannot be empty.")

                transaction = {
                    "transaction_date": transaction_date,
                    "amount": amount,
                    "description": description,
                    "payment_method": payment_method,
                    "category": category,
                    "deduplication_key": make_deduplication_key(
                        transaction_date,
                        amount,
                        description,
                        payment_method,
                        category,
                    ),
                }

                if amount < 0:
                    transaction["expense_amount"] = abs(amount)
                    result["valid_transactions"].append(transaction)
                else:
                    # Preserve credits/refunds in history, but don't create expenses.
                    result["credits"].append(transaction)

            except (ValueError, InvalidOperation) as exc:
                result["errors"].append(
                    {"row": row_number, "error": str(exc)}
                )

    except csv.Error as exc:
        result["errors"].append(
            {"row": 1, "error": f"Could not read CSV: {exc}"}
        )

    return result
