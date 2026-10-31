
import json
import logging
import os
import time

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app import (
    app,
    AWS_REGION,
    SNS_IMPORT_TOPIC_ARN,
    S3_RECEIPTS_BUCKET,
    get_s3_client,
)
from csv_import import validate_csv
from models import db, Category, Expense, ImportJob, ImportedTransaction

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("expensio.worker")

QUEUE_URL = os.getenv("SQS_CSV_IMPORT_QUEUE_URL", "").strip()
POLL_WAIT_SECONDS = 20
MAX_CSV_BYTES = 5 * 1024 * 1024


class PermanentImportError(ValueError):
    """An import error that will not be fixed by retrying the same file."""


def publish_import_notification(job, status):
    """Publish a minimal result event when an existing topic is configured."""
    if not SNS_IMPORT_TOPIC_ARN:
        return

    sns = boto3.client("sns", region_name=AWS_REGION)
    sns.publish(
        TopicArn=SNS_IMPORT_TOPIC_ARN,
        Subject=f"Expensio CSV import {status}",
        Message=json.dumps({
            "import_job_id": job.id,
            "status": status,
            "total_rows": job.total_rows,
            "imported_rows": job.imported_rows,
            "duplicate_rows": job.duplicate_rows,
            "invalid_rows": job.invalid_rows,
        }),
    )


def get_or_create_category(user_id, category_name):
    """Find or create a category without rolling back the outer transaction."""
    name = category_name.strip()

    if not name:
        raise PermanentImportError("A transaction has an empty category.")

    category = db.session.execute(
        select(Category).where(
            Category.user_id == user_id,
            func.lower(Category.name) == name.lower(),
        )
    ).scalar_one_or_none()

    if category is not None:
        return category

    try:
        # Use a savepoint so a category conflict does not roll back
        # the caller's transaction.
        with db.session.begin_nested():
            category = Category(user_id=user_id, name=name)
            db.session.add(category)
            db.session.flush()

        return category

    except IntegrityError:
        # A concurrent request may have created this category.
        category = db.session.execute(
            select(Category).where(
                Category.user_id == user_id,
                func.lower(Category.name) == name.lower(),
            )
        ).scalar_one_or_none()

        if category is None:
            # The integrity error was not explained by an existing
            # matching category. Let the caller handle it.
            raise

        return category


def process_import_message(message):
    """Process one SQS message containing a CSV import job."""
    body = json.loads(message["Body"])

    job_id = body.get("job_id", body.get("import_job_id"))
    user_id = body.get("user_id")
    object_key = body.get("object_key", body.get("s3_object_key"))
    event_type = body.get("event_type")
    schema_version = body.get("schema_version")

    if (
        not isinstance(job_id, int)
        or isinstance(job_id, bool)
        or job_id <= 0
        or not isinstance(user_id, int)
        or isinstance(user_id, bool)
        or user_id <= 0
        or not isinstance(object_key, str)
        or not object_key.strip()
        or (
            event_type is not None
            and event_type != "csv_import_requested"
        )
        or (
            schema_version is not None
            and schema_version != 1
        )
    ):
        raise ValueError("Invalid CSV import message fields.")

    with app.app_context():
        try:
            job = db.session.get(ImportJob, job_id)

            # The database job must match every identifier in the message.
            if (
                job is None
                or job.user_id != user_id
                or job.s3_object_key != object_key
            ):
                logger.error(
                    "SQS message does not match database job %s.", job_id
                )
                return "discard"

            # Repeated SQS deliveries must not import completed jobs again.
            if job.status == "completed":
                return "ack"

            if job.status == "failed":
                logger.warning("Job %s is already failed.", job_id)
                return "discard"

            job.status = "processing"
            job.error_summary = None
            db.session.commit()

            # Retrieve the uploaded CSV from private S3 storage.
            s3 = get_s3_client()
            response = s3.get_object(
                Bucket=S3_RECEIPTS_BUCKET,
                Key=object_key,
            )

            raw_content = response["Body"].read(MAX_CSV_BYTES + 1)

            if len(raw_content) > MAX_CSV_BYTES:
                raise PermanentImportError(
                    "CSV file exceeds the 5 MiB limit."
                )

            try:
                csv_text = raw_content.decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                raise PermanentImportError(
                    "CSV file must use UTF-8 encoding."
                ) from exc

            result = validate_csv(csv_text)

            imported_count = 0
            duplicate_count = 0
            invalid_count = len(result["errors"])

            transactions = (
                result["valid_transactions"] + result["credits"]
            )

            for item in transactions:
                deduplication_key = item["deduplication_key"]

                try:
                    with db.session.begin_nested():
                        existing = db.session.execute(
                            select(ImportedTransaction.id).where(
                                ImportedTransaction.user_id == user_id,
                                ImportedTransaction.deduplication_key
                                == deduplication_key,
                            )
                        ).scalar_one_or_none()

                        if existing is not None:
                            duplicate_count += 1
                            continue

                        category = get_or_create_category(
                            user_id, item["category"]
                        )

                        expense = None

                        # Negative amounts are expenses.
                        # Positive amounts are recorded as credits only.
                        if item["amount"] < 0:
                            expense = Expense(
                                user_id=user_id,
                                category_id=category.id,
                                amount=item["expense_amount"],
                                expense_date=item["transaction_date"],
                                description=item["description"],
                                payment_method=item["payment_method"],
                                source="csv",
                            )
                            db.session.add(expense)
                            db.session.flush()

                        transaction = ImportedTransaction(
                            user_id=user_id,
                            import_job_id=job_id,
                            expense_id=expense.id if expense else None,
                            transaction_date=item["transaction_date"],
                            amount=item["amount"],
                            description=item["description"],
                            payment_method=item["payment_method"],
                            deduplication_key=deduplication_key,
                        )
                        db.session.add(transaction)
                        db.session.flush()

                    # Increment only after the savepoint succeeds. Credits
                    # are imported history rows even without an expense.
                    imported_count += 1

                except IntegrityError:
                    # A uniqueness conflict can indicate a concurrent import.
                    # Verify that the transaction now exists before counting
                    # it as a duplicate; other integrity errors must retry.
                    existing = db.session.execute(
                        select(ImportedTransaction.id).where(
                            ImportedTransaction.user_id == user_id,
                            ImportedTransaction.deduplication_key
                            == deduplication_key,
                        )
                    ).scalar_one_or_none()

                    if existing is None:
                        raise

                    duplicate_count += 1

            job = db.session.get(ImportJob, job_id)
            if job is None or job.user_id != user_id:
                raise SQLAlchemyError(
                    "Import job disappeared during processing."
                )

            job.imported_rows = imported_count
            job.duplicate_rows = duplicate_count
            job.invalid_rows = invalid_count
            job.total_rows = len(transactions) + invalid_count
            job.status = "completed"
            job.error_summary = None
            db.session.commit()

            logger.info(
                "Job %s completed: imported=%s duplicates=%s invalid=%s",
                job_id,
                imported_count,
                duplicate_count,
                invalid_count,
            )
            try:
                publish_import_notification(job, "completed")
            except (BotoCoreError, ClientError):
                logger.exception(
                    "SNS notification failed after job %s completed",
                    job_id,
                )
            return "ack"

        except (BotoCoreError, ClientError):
            db.session.rollback()
            logger.exception("AWS operation failed for job %s", job_id)
            # Do not delete the message; SQS should retry it.
            raise

        except PermanentImportError as exc:
            db.session.rollback()
            logger.error("Permanent import error for job %s: %s", job_id, exc)

            try:
                job = db.session.get(ImportJob, job_id)
                if job is not None and job.user_id == user_id:
                    job.status = "failed"
                    job.error_summary = str(exc)[:1000]
                    db.session.commit()
                    try:
                        publish_import_notification(job, "failed")
                    except (BotoCoreError, ClientError):
                        logger.exception(
                            "SNS failure notification failed for job %s",
                            job_id,
                        )
            except SQLAlchemyError:
                db.session.rollback()
                logger.exception(
                    "Could not record permanent failure for job %s", job_id
                )
                # Keep the SQS message for retry if failure recording fails.
                raise

            return "discard"

        except Exception:
            db.session.rollback()
            logger.exception(
                "Unexpected error processing job %s; requesting SQS retry",
                job_id,
            )
            # Do not mark the job failed or acknowledge the message for an
            # unexpected error. A retry may succeed after a transient issue.
            raise


def run_worker():
    if not QUEUE_URL:
        raise RuntimeError(
            "SQS_CSV_IMPORT_QUEUE_URL is missing from .env"
        )

    if not S3_RECEIPTS_BUCKET:
        raise RuntimeError("S3_RECEIPTS_BUCKET is missing from .env")

    sqs = boto3.client("sqs", region_name=AWS_REGION)
    logger.info("CSV worker started. Waiting for SQS messages.")

    while True:
        try:
            response = sqs.receive_message(
                QueueUrl=QUEUE_URL,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=POLL_WAIT_SECONDS,
                VisibilityTimeout=120,
            )

            for message in response.get("Messages", []):
                try:
                    outcome = process_import_message(message)

                    if outcome in ("ack", "discard"):
                        sqs.delete_message(
                            QueueUrl=QUEUE_URL,
                            ReceiptHandle=message["ReceiptHandle"],
                        )

                except Exception:
                    # Leave the message for SQS retry/redrive policy.
                    logger.exception("Message processing will be retried.")

        except (BotoCoreError, ClientError):
            logger.exception("Could not poll SQS. Retrying shortly.")
            time.sleep(5)


if __name__ == "__main__":
    run_worker()
