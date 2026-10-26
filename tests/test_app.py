
import pytest

from app import app as flask_app


@pytest.fixture()
def client():
    flask_app.config.update(TESTING=True)

    with flask_app.test_client() as test_client:
        yield test_client


def test_health_endpoint(client):
    response = client.get("/health")

    assert response.status_code == 200


def test_dashboard_loads(client):
    response = client.get("/")

    assert response.status_code == 200


def test_expenses_endpoint_returns_json(client):
    response = client.get("/api/expenses")

    assert response.status_code == 200
    assert response.is_json
    assert isinstance(response.get_json(), list)

def test_csv_preview_endpoint_validates_upload(client):
    csv_content = (
        "transaction_date,amount,description,payment_method,category\n"
        "2026-10-25,-125.50,Lunch,UPI,Food\n"
        "2026-10-25,500.00,Refund,UPI,Shopping\n"
        "2026-10-25,0,Invalid,UPI,Food\n"
    )

    response = client.post(
        "/api/imports/csv/preview",
        data={
            "file": (
                __import__("io").BytesIO(csv_content.encode("utf-8")),
                "statement.csv",
            )
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["expense_count"] == 1
    assert data["credit_count"] == 1
    assert data["error_count"] == 1

def test_csv_preview_rejects_missing_file(client):
    response = client.post("/api/imports/csv/preview")

    assert response.status_code == 400
    assert "error" in response.get_json()


def test_csv_preview_rejects_non_csv_file(client):
    import io

    response = client.post(
        "/api/imports/csv/preview",
        data={
            "file": (
                io.BytesIO(b"not a csv"),
                "statement.txt",
            )
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert "Only .csv files" in response.get_json()["error"]


def test_csv_preview_rejects_oversized_file(client):
    import io

    oversized_content = b"a" * (5 * 1024 * 1024 + 1)

    response = client.post(
        "/api/imports/csv/preview",
        data={
            "file": (
                io.BytesIO(oversized_content),
                "statement.csv",
            )
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 413
