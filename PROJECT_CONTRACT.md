## 4. Database Schema — Proposed

### users
- id: primary key
- name
- email: unique, required
- password_hash
- created_at

### categories
- id: primary key
- user_id: foreign key to users, nullable only if shared system categories are supported
- name
- created_at

### expenses
- id: primary key
- user_id: foreign key to users
- category_id: foreign key to categories
- amount: positive numeric value
- expense_date
- description
- payment_method
- receipt_object_key: optional S3 object key
- source: manual or csv
- created_at
- updated_at

### budgets
- id: primary key
- user_id: foreign key to users
- category_id: optional foreign key to categories; null means overall budget
- month: first day of the budget month
- amount_limit: positive numeric value
- created_at
- updated_at

### import_jobs
- id: primary key
- user_id: foreign key to users
- s3_object_key
- status: queued, processing, completed or failed
- total_rows
- imported_rows
- duplicate_rows
- invalid_rows
- error_summary
- created_at
- updated_at

### imported_transactions
- id: primary key
- user_id: foreign key to users
- import_job_id: foreign key to import_jobs
- expense_id: optional foreign key to expenses
- transaction_date
- amount
- description
- payment_method
- deduplication_key
- created_at

Use appropriate foreign keys, indexes, constraints and timestamps. Agree on exact PostgreSQL types and deletion behavior before implementation.

## 6. CSV Import and Queue Contract — Proposed

- Valid CSV transactions are automatically created as expenses.
- Invalid rows are rejected and counted in the import summary.
- Duplicate transactions are not imported twice.
- The worker processes import jobs asynchronously on EC2.
- Import status and row counts are saved in PostgreSQL.
- The worker acknowledges an SQS message only after successful processing or a deliberately handled terminal outcome.
- Processing must be idempotent because SQS can deliver a message more than once.
- SQS message schema: job_id, user_id, object_key, event_type and schema_version.
- Never trust a message's user_id alone for authorization; verify ownership through the import job record.
- SNS notifications are sent for configured import outcomes.

These are proposed contracts pending Maria's review and joint approval.
