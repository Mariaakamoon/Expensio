import io
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app import app as flask_app


def test_preview_valid_and_invalid_rows():
    flask_app.config.update(TESTING=True)
    csv = (
        "transaction_date,amount,description,payment_method,category\n"
        "2026-10-20,-25.00,Lunch,UPI,Food\n"
        "2026-10-21,not-money,Invalid,Card,Food\n"
    )

    with flask_app.test_client() as client:
        response = client.post(
            "/api/imports/csv/preview",
            data={"file": (io.BytesIO(csv.encode()), "expenses.csv")},
            content_type="multipart/form-data",
        )

    assert response.status_code == 200
    result = response.get_json()
    assert result["expense_count"] == 1
    assert result["credit_count"] == 0
    assert result["error_count"] == 1


def test_preview_rejects_invalid_headers():
    flask_app.config.update(TESTING=True)

    with flask_app.test_client() as client:
        response = client.post(
            "/api/imports/csv/preview",
            data={"file": (io.BytesIO(b"date,amount\n2026-10-20,-1\n"), "bad.csv")},
            content_type="multipart/form-data",
        )

    assert response.status_code == 200
    assert response.get_json()["error_count"] == 1


def test_submit_enqueues_credit_only_csv():
    flask_app.config.update(TESTING=True)
    csv = (
        "transaction_date,amount,description,payment_method,category\n"
        "2026-10-20,25.00,Refund,UPI,Food\n"
    )
    fake_session = MagicMock()
    fake_sqs = MagicMock()
    fake_s3 = MagicMock()

    def assign_job_id(job):
        job.id = 42

    fake_session.add.side_effect = assign_job_id

    with patch("app.get_dev_user", return_value=SimpleNamespace(id=7)), \
         patch("app.db.session", fake_session), \
         patch("app.get_s3_client", return_value=fake_s3), \
         patch("app.boto3.client", return_value=fake_sqs), \
         patch("app.S3_RECEIPTS_BUCKET", "existing-bucket"), \
         patch("app.SQS_CSV_IMPORT_QUEUE_URL", "existing-queue"):
        with flask_app.test_client() as client:
            response = client.post(
                "/api/imports/csv/submit",
                data={"file": (io.BytesIO(csv.encode()), "credits.csv")},
                content_type="multipart/form-data",
            )

    assert response.status_code == 202
    assert response.get_json()["import_job_id"] == 42
    fake_sqs.send_message.assert_called_once()
    body = fake_sqs.send_message.call_args.kwargs["MessageBody"]
    assert '"job_id": 42' in body
    assert '"event_type": "csv_import_requested"' in body


def test_import_status_is_user_scoped():
    flask_app.config.update(TESTING=True)
    job = SimpleNamespace(
        id=42,
        user_id=7,
        status="completed",
        total_rows=2,
        imported_rows=1,
        duplicate_rows=1,
        invalid_rows=0,
        error_summary=None,
        created_at=datetime(2026, 10, 20, tzinfo=timezone.utc),
        updated_at=datetime(2026, 10, 20, tzinfo=timezone.utc),
    )
    result = MagicMock()
    result.scalar_one_or_none.return_value = job

    with patch("app.get_dev_user", return_value=SimpleNamespace(id=7)), \
         patch("app.db.session.execute", return_value=result):
        with flask_app.test_client() as client:
            response = client.get("/api/imports/42")

    assert response.status_code == 200
    assert response.get_json()["status"] == "completed"
    assert "s3_object_key" not in response.get_json()
