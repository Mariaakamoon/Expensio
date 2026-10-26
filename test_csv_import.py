
from decimal import Decimal

from csv_import import validate_csv


def test_valid_expense_is_accepted():
    csv_text = (
        "transaction_date,amount,description,payment_method,category\n"
        "2026-10-25,-125.50,Lunch,UPI,Food\n"
    )

    result = validate_csv(csv_text)

    assert len(result["valid_transactions"]) == 1
    assert result["valid_transactions"][0]["expense_amount"] == Decimal("125.50")
    assert len(result["errors"]) == 0


def test_positive_amount_is_kept_as_credit():
    csv_text = (
        "transaction_date,amount,description,payment_method,category\n"
        "2026-10-25,500.00,Refund,UPI,Shopping\n"
    )

    result = validate_csv(csv_text)

    assert len(result["credits"]) == 1
    assert len(result["valid_transactions"]) == 0


def test_zero_amount_is_rejected():
    csv_text = (
        "transaction_date,amount,description,payment_method,category\n"
        "2026-10-25,0,Invalid,UPI,Food\n"
    )

    result = validate_csv(csv_text)

    assert len(result["errors"]) == 1


def test_invalid_date_is_rejected():
    csv_text = (
        "transaction_date,amount,description,payment_method,category\n"
        "25-10-2026,-50,Snack,Cash,Food\n"
    )

    result = validate_csv(csv_text)

    assert len(result["errors"]) == 1


def test_duplicate_transactions_have_same_key():
    csv_text = (
        "transaction_date,amount,description,payment_method,category\n"
        "2026-10-25,-125.50,Lunch,UPI,Food\n"
        "2026-10-25,-125.50,Lunch,UPI,Food\n"
    )

    result = validate_csv(csv_text)

    assert len(result["valid_transactions"]) == 2
    first_key = result["valid_transactions"][0]["deduplication_key"]
    second_key = result["valid_transactions"][1]["deduplication_key"]
    assert first_key == second_key
    assert len(first_key) == 64


def test_missing_required_header_is_reported():
    csv_text = (
        "transaction_date,amount,description,payment_method\n"
        "2026-10-25,-50,Snack,Cash\n"
    )

    result = validate_csv(csv_text)

    assert len(result["errors"]) == 1
    assert "Missing required headers" in result["errors"][0]["error"]
