# Expensio — Database and CSV Import Contract

**Status:** Proposed implementation contract — approved direction, with exact rules documented below  
**Database:** PostgreSQL  
**ORM:** SQLAlchemy  
**Application:** Flask  
**Queue:** Amazon SQS  
**File storage:** Private Amazon S3 bucket  
**Worker:** Python worker running on EC2

## 1. General rules

- Every user-owned record must be scoped to its `user_id`.
- Never store plain-text passwords.
- Use `NUMERIC(12,2)` for money; do not use floating-point types for monetary values.
- Use `DATE` for transaction and expense dates.
- Use `TIMESTAMPTZ` for timestamps.
- Use database constraints as well as application validation.
- Store receipt and uploaded CSV files in private S3. Store object keys in PostgreSQL, not file contents.
- Do not implement models until the team has reviewed this contract and the current SQLite prototype transition has been planned.

## 2. Database tables

### 2.1 `users`

| Column | PostgreSQL type | Rules |
|---|---|---|
| `id` | `BIGINT GENERATED ALWAYS AS IDENTITY` | Primary key |
| `name` | `VARCHAR(120)` | Required |
| `email` | `VARCHAR(254)` | Required; unique |
| `password_hash` | `VARCHAR(255)` | Required; never plain-text |
| `created_at` | `TIMESTAMPTZ` | Required; defaults to current timestamp |

### 2.2 `categories`

| Column | PostgreSQL type | Rules |
|---|---|---|
| `id` | `BIGINT GENERATED ALWAYS AS IDENTITY` | Primary key |
| `user_id` | `BIGINT` | Required; FK to `users.id`, `ON DELETE CASCADE` |
| `name` | `VARCHAR(80)` | Required |
| `created_at` | `TIMESTAMPTZ` | Required; defaults to current timestamp |

- A category belongs to one user.
- Unique category name per user: `UNIQUE(user_id, name)`.
- An expense can reference only a category owned by the same user. Enforce this in application logic and, where practical, with a composite foreign key.

### 2.3 `expenses`

| Column | PostgreSQL type | Rules |
|---|---|---|
| `id` | `BIGINT GENERATED ALWAYS AS IDENTITY` | Primary key |
| `user_id` | `BIGINT` | Required; FK to `users.id`, `ON DELETE CASCADE` |
| `category_id` | `BIGINT` | Required; FK to `categories.id`; category must belong to the same user |
| `amount` | `NUMERIC(12,2)` | Required; must be greater than zero |
| `expense_date` | `DATE` | Required |
| `description` | `TEXT` | Optional |
| `payment_method` | `VARCHAR(40)` | Optional |
| `receipt_object_key` | `TEXT` | Optional private S3 object key |
| `source` | `VARCHAR(10)` | Required; only `manual` or `csv` |
| `created_at` | `TIMESTAMPTZ` | Required; defaults to current timestamp |
| `updated_at` | `TIMESTAMPTZ` | Required; set on creation and update |

- Index expenses for common user/date and user/category queries.
- Deleting an expense must not delete its historical `imported_transactions` record; set that record's `expense_id` to `NULL`.
- Remove a receipt object from S3 when its associated receipt/expense is permanently deleted, using safe application logic. Do not make the bucket public.

### 2.4 `budgets`

| Column | PostgreSQL type | Rules |
|---|---|---|
| `id` | `BIGINT GENERATED ALWAYS AS IDENTITY` | Primary key |
| `user_id` | `BIGINT` | Required; FK to `users.id`, `ON DELETE CASCADE` |
| `category_id` | `BIGINT` | Optional FK to `categories.id`; if set, it must belong to the same user |
| `month` | `DATE` | Required; must be the first day of a month |
| `amount_limit` | `NUMERIC(12,2)` | Required; must be greater than zero |
| `created_at` | `TIMESTAMPTZ` | Required; defaults to current timestamp |
| `updated_at` | `TIMESTAMPTZ` | Required; set on creation and update |

- `category_id IS NULL` means an overall monthly budget.
- A user can have at most one overall budget per month. Enforce with a partial unique index on `(user_id, month)` where `category_id IS NULL`.
- A user can have at most one budget per category per month. Enforce with a unique constraint/index on `(user_id, month, category_id)` where `category_id IS NOT NULL`.
- Restrict category deletion while expenses or budgets reference it.

### 2.5 `import_jobs`

| Column | PostgreSQL type | Rules |
|---|---|---|
| `id` | `BIGINT GENERATED ALWAYS AS IDENTITY` | Primary key |
| `user_id` | `BIGINT` | Required; FK to `users.id`, `ON DELETE CASCADE` |
| `s3_object_key` | `TEXT` | Required; private S3 key for the uploaded CSV |
| `status` | `VARCHAR(20)` | Required; one of `queued`, `processing`, `completed`, `failed` |
| `total_rows` | `INTEGER` | Required; default 0; non-negative |
| `imported_rows` | `INTEGER` | Required; default 0; non-negative |
| `duplicate_rows` | `INTEGER` | Required; default 0; non-negative |
| `invalid_rows` | `INTEGER` | Required; default 0; non-negative |
| `error_summary` | `TEXT` | Optional |
| `created_at` | `TIMESTAMPTZ` | Required; defaults to current timestamp |
| `updated_at` | `TIMESTAMPTZ` | Required; set on creation and update |

- Add an index on `(user_id, created_at)` and on `status`.
- `total_rows` counts data rows, excluding the header.
- `imported_rows` counts rows that successfully created expenses.
- `duplicate_rows` counts valid rows skipped because they match an existing transaction.
- `invalid_rows` counts rows rejected by validation.
- A terminal `completed` job may have invalid and/or duplicate rows if valid rows were processed.

### 2.6 `imported_transactions`

| Column | PostgreSQL type | Rules |
|---|---|---|
| `id` | `BIGINT GENERATED ALWAYS AS IDENTITY` | Primary key |
| `user_id` | `BIGINT` | Required; FK to `users.id`, `ON DELETE CASCADE` |
| `import_job_id` | `BIGINT` | Required; FK to `import_jobs.id`, `ON DELETE CASCADE` |
| `expense_id` | `BIGINT` | Optional FK to `expenses.id`, `ON DELETE SET NULL` |
| `transaction_date` | `DATE` | Required |
| `amount` | `NUMERIC(12,2)` | Required; may be positive or negative to preserve source sign; zero is invalid |
| `description` | `TEXT` | Optional |
| `payment_method` | `VARCHAR(40)` | Optional |
| `deduplication_key` | `VARCHAR(64)` | Required; stable SHA-256 hex digest |
| `created_at` | `TIMESTAMPTZ` | Required; defaults to current timestamp |

- Use a unique constraint on `(user_id, deduplication_key)`.
- Add indexes for `(user_id, transaction_date)` and `import_job_id`.
- A transaction's `expense_id` is nullable so the import history can survive expense deletion.
- The application must verify that `import_job_id` belongs to the same `user_id`.

## 3. Category and deletion behavior

- Deleting a user cascades to that user's categories, expenses, budgets, import jobs and imported transactions.
- Deleting a category is restricted while an expense or budget references it.
- Deleting an expense sets matching `imported_transactions.expense_id` to `NULL`; it must not erase import history.
- S3 object deletion is an application workflow. A database cascade does not delete files from S3.
- User authorization must be enforced on every read, update, delete, receipt download and import-status request.

## 4. CSV file contract

### 4.1 Required header

The first version accepts these exact, case-insensitive column names:

- `transaction_date`
- `amount`
- `description`
- `payment_method`
- `category`

Whitespace around header names and cell values is trimmed. The file must contain all five columns. Extra columns are ignored in version 1.

### 4.2 Row validation

- `transaction_date` must be a valid ISO date in `YYYY-MM-DD` format.
- `amount` must parse as a decimal with no more than two fractional digits and must not be zero.
- Negative amounts represent money leaving the account and may create an expense with `abs(amount)`.
- Positive amounts represent credits/refunds and are recorded in import history but do not create an expense in version 1.
- `description` may be empty; trim whitespace.
- `payment_method` may be empty; trim whitespace.
- `category` must be non-empty and must match or create a category belonging to the importing user. Category auto-creation should be implemented consistently and documented in the UI.
- Rows that fail validation count as invalid; do not create an expense for them.
- Do not silently convert a credit into an expense.

### 4.3 Duplicate detection

For each valid row, normalize the values and calculate a SHA-256 digest from the canonical representation of:

`user_id | transaction_date | signed_amount_to_2dp | normalized_description | normalized_payment_method`

Normalize text by trimming whitespace and collapsing repeated internal whitespace. Use case-folding for description and payment method before hashing. Category is deliberately excluded so categorizing the same bank transaction differently does not bypass duplicate detection.

- Enforce uniqueness on `(user_id, deduplication_key)` in PostgreSQL.
- The worker must handle a uniqueness conflict as a duplicate, not as a fatal job error.
- A repeated SQS delivery or repeated CSV upload must not create duplicate expenses.
- For an already-seen transaction, do not create another expense. Count it as a duplicate in the current job.
- A valid negative-amount transaction creates an expense and links its `expense_id` to the imported transaction record.
- A positive-amount credit/refund is recorded with `expense_id = NULL` and is not counted as an imported expense.

## 5. SQS message contract

Every message body must be a JSON object with:

```json
{
  "job_id": 123,
  "user_id": 456,
  "object_key": "imports/user-456/job-123.csv",
  "event_type": "csv_import_requested",
  "schema_version": 1
}
```

- `job_id` and `user_id` are positive integers.
- `object_key` is the exact private S3 object key uploaded for the job.
- `event_type` must be `csv_import_requested` in version 1.
- `schema_version` must be the integer `1`.
- Treat message values as untrusted. Load the job from PostgreSQL and verify that the job's `user_id` and `s3_object_key` match the message. Do not authorize access based only on the message's `user_id`.
- Never include passwords, credentials, access tokens or other secrets in the message.

## 6. Worker lifecycle, retries and idempotency

1. Receive an SQS message.
2. Validate the message structure and schema version.
3. Load the job and verify ownership/key consistency.
4. Atomically claim the job if it is `queued`; mark it `processing`.
5. Read the CSV from private S3 and validate rows.
6. Process rows using database transactions and uniqueness constraints to protect against retries.
7. Save row counts and an error summary.
8. Mark the job `completed` after a deliberate terminal processing outcome, including a partially invalid file; mark it `failed` for an unrecoverable job-level error.
9. Send an SNS notification for the configured terminal outcome.
10. Delete/acknowledge the SQS message only after successful processing or a deliberately handled terminal outcome.

- Temporary infrastructure/database failures must be retried and must not be marked as successful.
- Configure an SQS visibility timeout longer than normal processing time and configure a dead-letter queue for repeated failures.
- If a message is redelivered, inspect the persisted job state and deduplication records before doing work again.
- The job status update, imported transaction inserts, expense inserts and counts must be committed consistently. Use transactions and safe retry handling.
- Do not send duplicate notifications on every retry; use a persisted notification marker or another idempotent strategy if exact-once notification behavior is required.

## 7. Indexes and constraints checklist

- Unique `users.email`.
- Unique `(categories.user_id, categories.name)`.
- Positive `expenses.amount`; `expenses.source IN ('manual', 'csv')`.
- Category ownership enforced for expenses and category budgets.
- `budgets.month` is the first day of a month; positive `amount_limit`.
- Partial unique indexes for overall budgets and category budgets.
- `import_jobs.status` check constraint and non-negative row-count constraints.
- Unique `(imported_transactions.user_id, imported_transactions.deduplication_key)`.
- Appropriate indexes for user/date, user/category, job status and import-job lookups.
- Foreign keys use the deletion behavior specified above.

## 8. Implementation order

1. Review and commit this contract.
2. Finalize authentication and user ownership behavior.
3. Implement SQLAlchemy models and constraints for PostgreSQL.
4. Add schema migrations; do not rely on `create_all()` for production schema changes.
5. Test models and constraints against PostgreSQL.
6. Implement CSV parsing and validation independently of SQS.
7. Implement S3 upload and `import_jobs` creation.
8. Add SQS publishing and the EC2 worker.
9. Add SNS terminal notifications and monitoring.
10. Test retries, duplicate uploads, partial-invalid files, refunds, authorization and failure recovery.
11. Plan the SQLite prototype transition only after the new schema and tests are ready.

## 9. Approval record

- Maria: approved overall design and decisions in team discussion.
- Aarya: approved overall design and decisions in team discussion.
- Exact schema and CSV rules in this document should be reviewed by both teammates before implementation.

