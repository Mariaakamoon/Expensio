
import json

import pytest

from worker import process_import_message


def make_message(body):
    return {"Body": json.dumps(body)}


def test_worker_rejects_missing_job_id():
    message = make_message({
        "user_id": 1,
        "object_key": "imports/test.csv",
    })

    with pytest.raises(ValueError, match="Invalid CSV import message"):
        process_import_message(message)


def test_worker_rejects_non_positive_job_id():
    message = make_message({
        "job_id": 0,
        "user_id": 1,
        "object_key": "imports/test.csv",
    })

    with pytest.raises(ValueError, match="Invalid CSV import message"):
        process_import_message(message)


def test_worker_rejects_boolean_job_id():
    message = make_message({
        "job_id": True,
        "user_id": 1,
        "object_key": "imports/test.csv",
    })

    with pytest.raises(ValueError, match="Invalid CSV import message"):
        process_import_message(message)


def test_worker_rejects_missing_user_id():
    message = make_message({
        "job_id": 1,
        "object_key": "imports/test.csv",
    })

    with pytest.raises(ValueError, match="Invalid CSV import message"):
        process_import_message(message)


def test_worker_rejects_empty_object_key():
    message = make_message({
        "job_id": 1,
        "user_id": 1,
        "object_key": "",
    })

    with pytest.raises(ValueError, match="Invalid CSV import message"):
        process_import_message(message)


def test_worker_rejects_invalid_json():
    message = {"Body": "this is not valid JSON"}

    with pytest.raises(json.JSONDecodeError):
        process_import_message(message)

from unittest.mock import patch


def test_worker_discards_message_for_missing_job():
    message = make_message({
        "job_id": 999999,
        "user_id": 1,
        "object_key": "imports/test.csv",
    })

    with patch("worker.db.session.get", return_value=None):
        outcome = process_import_message(message)

    assert outcome == "discard"

def test_worker_acknowledges_completed_job_without_reprocessing():
    from types import SimpleNamespace

    message = make_message({
        "job_id": 123,
        "user_id": 1,
        "object_key": "imports/test.csv",
    })

    completed_job = SimpleNamespace(
        id=123,
        user_id=1,
        s3_object_key="imports/test.csv",
        status="completed",
    )

    with patch("worker.db.session.get", return_value=completed_job):
        with patch("worker.get_s3_client") as mock_s3:
            outcome = process_import_message(message)

    assert outcome == "ack"
    mock_s3.assert_not_called()

def test_worker_discards_already_failed_job():
    from types import SimpleNamespace

    message = make_message({
        "job_id": 124,
        "user_id": 1,
        "object_key": "imports/test.csv",
    })

    failed_job = SimpleNamespace(
        id=124,
        user_id=1,
        s3_object_key="imports/test.csv",
        status="failed",
    )

    with patch("worker.db.session.get", return_value=failed_job):
        with patch("worker.get_s3_client") as mock_s3:
            outcome = process_import_message(message)

    assert outcome == "discard"
    mock_s3.assert_not_called()

def test_worker_retries_when_database_lookup_fails():
    from unittest.mock import patch
    from sqlalchemy.exc import SQLAlchemyError

    message = make_message({
        "job_id": 125,
        "user_id": 1,
        "object_key": "imports/test.csv",
    })

    with patch(
        "worker.db.session.get",
        side_effect=SQLAlchemyError("Temporary database failure"),
    ):
        with pytest.raises(SQLAlchemyError):
            process_import_message(message)

def test_worker_deletes_message_after_successful_processing():
    from unittest.mock import patch

    message = {
        "Body": "{}",
        "ReceiptHandle": "test-receipt-handle",
    }

    fake_sqs = __import__("unittest.mock", fromlist=["MagicMock"]).MagicMock()
    fake_sqs.receive_message.side_effect = [
        {"Messages": [message]},
        KeyboardInterrupt(),
    ]

    with patch("worker.boto3.client", return_value=fake_sqs):
        with patch("worker.QUEUE_URL", "https://example.com/test-queue"):
            with patch("worker.process_import_message", return_value="ack"):
                with patch("worker.S3_RECEIPTS_BUCKET", "test-bucket"):
                    with pytest.raises(KeyboardInterrupt):
                        from worker import run_worker
                        run_worker()

    fake_sqs.delete_message.assert_called_once_with(
        QueueUrl="https://example.com/test-queue",
        ReceiptHandle="test-receipt-handle",
    )

def test_worker_does_not_delete_message_when_processing_raises():
    from unittest.mock import MagicMock, patch

    message = {
        "Body": "{}",
        "ReceiptHandle": "retry-receipt-handle",
    }

    fake_sqs = MagicMock()
    fake_sqs.receive_message.side_effect = [
        {"Messages": [message]},
        KeyboardInterrupt(),
    ]

    with patch("worker.boto3.client", return_value=fake_sqs):
        with patch("worker.QUEUE_URL", "https://example.com/test-queue"):
            with patch(
                "worker.process_import_message",
                side_effect=RuntimeError("Temporary failure"),
            ):
                with pytest.raises(KeyboardInterrupt):
                    from worker import run_worker
                    run_worker()

    fake_sqs.delete_message.assert_not_called()


