# Expensio â€” Project Contract

**Project:** Expensio â€” Cloud-Based Expense Tracking & Reporting Platform
**Status:** Proposed â€” pending final review by both team members
**Cloud provider:** Amazon Web Services (AWS)
**Proposed AWS region:** Mumbai (`ap-south-1`)
**Backend:** Python Flask
**Database:** Amazon RDS for PostgreSQL
**Repository:** Shared GitHub repository

---

## 1. Project Overview

Expensio is a cloud-based expense tracking and reporting application that allows users to manage expenses, organize transactions, upload receipts, import bank statements, create budgets, and view financial summaries.

The application will use AWS infrastructure to demonstrate cloud networking, database hosting, object storage, asynchronous processing, notifications, monitoring, and cost management.

### 1.1 Objectives

- Build a functional expense management web application.
- Store user and financial records in PostgreSQL.
- Store uploaded receipts and bank statement files in Amazon S3.
- Process CSV imports asynchronously using Amazon SQS and a separate Python worker.
- Provide budget tracking, dashboards, and reports.
- Use IAM, private networking, and Parameter Store to protect resources and secrets.
- Monitor application errors and AWS spending.

## 2. Scope and Features

### 2.1 User Authentication

- Register and log in users.
- Hash passwords securely; never store plaintext passwords.
- Associate each user's expenses, categories, budgets, and import jobs with that user.
- Prevent users from accessing another user's data.

### 2.2 Expense Management

- Add, view, edit, and delete expenses.
- Assign each expense to a category.
- Store amount, date, description, and payment method.
- Upload an optional receipt.
- Display expenses with useful filters, such as date and category.

### 2.3 Categories

- Allow users to create and manage their own categories.
- Prevent duplicate category names for the same user.
- Prevent a user from assigning an expense to another user's category.

### 2.4 CSV Bank Statement Import

- Accept CSV bank statement uploads.
- Store the original uploaded file in a private S3 bucket.
- Create an import job and enqueue a message in SQS.
- Process the import asynchronously using a separate Python worker process running on EC2.
- Validate rows and detect duplicates.
- Convert valid, non-duplicate transactions into expenses.
- Display import status and counts for imported, duplicate, and invalid rows.

### 2.5 Budget Management

- Allow users to create monthly overall budgets and category-specific budgets.
- Show budget limits, spending, and remaining amounts.
- Calculate spending from the user's recorded expenses.
- Support budget-related notifications when configured thresholds are reached.

### 2.6 Dashboard and Reports

- Display total spending for a selected period.
- Show spending by category.
- Show monthly spending trends.
- Display budget utilization.
- Provide useful date and category filters.

### 2.7 Notifications and Job Status

- Use Amazon SNS for relevant notifications.
- Use CloudWatch for application logs and monitoring.
- Provide import-job status: queued, processing, completed, or failed.
- Record errors in a way that helps debugging without exposing secrets or sensitive financial data.

## 3. Technology Stack

| Layer | Technology |
|---|---|
| Frontend | HTML, CSS, JavaScript, Bootstrap |
| Backend | Python, Flask |
| Database | Amazon RDS for PostgreSQL |
| ORM | SQLAlchemy |
| File storage | Amazon S3 |
| Cloud SDK | Boto3 |
| Asynchronous queue | Amazon SQS |
| Worker | Separate Python process on EC2 |
| Notifications | Amazon SNS |
| Configuration and secrets | AWS Systems Manager Parameter Store |
| Compute | Amazon EC2 |
| Networking | Amazon VPC, subnets, route tables, Internet Gateway, security groups |
| Logging and alarms | Amazon CloudWatch |
| Cost monitoring | AWS Budgets |
| Version control | Git and GitHub |

### 3.1 Scope Restrictions

- Do not introduce Docker, Kubernetes, Lambda, or other additional services unless both team members agree that they are necessary.
- The Flask application and Python worker must run as separate processes on EC2.
- Do not use a fully serverless architecture.
- Prefer the simplest implementation that satisfies the project requirements.

## 4. Proposed Database Schema

**Database:** PostgreSQL. All tables and constraints below are proposed until both team members approve them.

Use `BIGINT GENERATED ALWAYS AS IDENTITY` for primary keys, `TIMESTAMPTZ` for timestamps, `DATE` for calendar dates, and `NUMERIC(12,2)` for monetary amounts.

### 4.1 `users`

| Column | Type | Rules |
|---|---|---|
| id | BIGINT | Primary key, identity |
| name | VARCHAR(100) | Required |
| email | VARCHAR(255) | Required, unique |
| password_hash | VARCHAR(255) | Required |
| created_at | TIMESTAMPTZ | Required, defaults to current timestamp |

### 4.2 `categories`

| Column | Type | Rules |
|---|---|---|
| id | BIGINT | Primary key, identity |
| user_id | BIGINT | Required, FK to users.id |
| name | VARCHAR(80) | Required |
| created_at | TIMESTAMPTZ | Required, defaults to current timestamp |

Constraints:

- `UNIQUE (user_id, name)`
- `UNIQUE (user_id, id)` to support ownership-enforcing composite foreign keys.
- Category names are unique per user, not globally.

### 4.3 `expenses`

| Column | Type | Rules |
|---|---|---|
| id | BIGINT | Primary key, identity |
| user_id | BIGINT | Required, FK to users.id |
| category_id | BIGINT | Required |
| amount | NUMERIC(12,2) | Required, greater than zero |
| expense_date | DATE | Required |
| description | VARCHAR(500) | Optional |
| payment_method | VARCHAR(40) | Optional |
| receipt_object_key | VARCHAR(1024) | Optional |
| source | VARCHAR(10) | Required; `manual` or `csv` |
| created_at | TIMESTAMPTZ | Required, defaults to current timestamp |
| updated_at | TIMESTAMPTZ | Required, defaults to current timestamp |

Constraints and indexes:

- `UNIQUE (user_id, id)` for ownership-enforcing composite foreign keys.
- Composite foreign key `(user_id, category_id)` references `categories(user_id, id)`.
- `CHECK (amount > 0)`.
- `CHECK (source IN ('manual', 'csv'))`.
- Index on `(user_id, expense_date)`.
- Index on `(user_id, category_id, expense_date)`.

### 4.4 `budgets`

| Column | Type | Rules |
|---|---|---|
| id | BIGINT | Primary key, identity |
| user_id | BIGINT | Required, FK to users.id |
| category_id | BIGINT | Optional; NULL means overall budget |
| month | DATE | Required; first day of the budget month |
| amount_limit | NUMERIC(12,2) | Required, greater than zero |
| created_at | TIMESTAMPTZ | Required, defaults to current timestamp |
| updated_at | TIMESTAMPTZ | Required, defaults to current timestamp |

Constraints and indexes:

- Composite foreign key `(user_id, category_id)` references `categories(user_id, id)` when `category_id` is not NULL.
- `CHECK (amount_limit > 0)`.
- `CHECK (EXTRACT(DAY FROM month) = 1)`.
- Unique partial index on `(user_id, month)` where `category_id IS NULL`.
- Unique partial index on `(user_id, category_id, month)` where `category_id IS NOT NULL`.

These indexes prevent duplicate overall budgets and duplicate category budgets for the same user and month.

### 4.5 `import_jobs`

| Column | Type | Rules |
|---|---|---|
| id | BIGINT | Primary key, identity |
| user_id | BIGINT | Required, FK to users.id |
| s3_object_key | VARCHAR(1024) | Required |
| status | VARCHAR(20) | Required |
| total_rows | INTEGER | Required, defaults to 0 |
| imported_rows | INTEGER | Required, defaults to 0 |
| duplicate_rows | INTEGER | Required, defaults to 0 |
| invalid_rows | INTEGER | Required, defaults to 0 |
| error_summary | TEXT | Optional |
| created_at | TIMESTAMPTZ | Required, defaults to current timestamp |
| updated_at | TIMESTAMPTZ | Required, defaults to current timestamp |

Constraints:

- `UNIQUE (user_id, id)`.
- `CHECK (status IN ('queued', 'processing', 'completed', 'failed'))`.
- All row counts must be non-negative.
- Composite foreign key `(user_id, s3_object_key)` is not required; the S3 key is validated by application logic.
- Composite ownership reference `(user_id, id)` will be used by `imported_transactions`.

### 4.6 `imported_transactions`

This table records the result of importing individual bank statement transactions and helps prevent duplicate imports.

| Column | Type | Rules |
|---|---|---|
| id | BIGINT | Primary key, identity |
| user_id | BIGINT | Required, FK to users.id |
| import_job_id | BIGINT | Required |
| expense_id | BIGINT | Optional |
| transaction_date | DATE | Required |
| amount | NUMERIC(12,2) | Required, greater than zero |
| description | VARCHAR(500) | Optional |
| payment_method | VARCHAR(40) | Optional |
| source_identifier | VARCHAR(100) | Optional; identifies the bank or statement source |
| bank_transaction_id | VARCHAR(255) | Optional |
| deduplication_key | VARCHAR(64) | Required |
| created_at | TIMESTAMPTZ | Required, defaults to current timestamp |

Constraints and indexes:

- Composite foreign key `(user_id, import_job_id)` references `import_jobs(user_id, id)`.
- Composite foreign key `(user_id, expense_id)` references `expenses(user_id, id)`.
- A unique partial index on `expense_id` where `expense_id IS NOT NULL`.
- `UNIQUE (user_id, deduplication_key)`.
- `CHECK (amount > 0)`.

`source_identifier` and `bank_transaction_id` together identify a bank transaction when the source supplies a stable transaction ID. The application must generate a deterministic deduplication key.

### 4.7 CSV Import Rules

1. Validate the CSV format, required columns, dates, amounts, and row values.
2. Normalize transaction data consistently before generating a deduplication key.
3. When a stable bank transaction ID is available, include the source identifier and bank transaction ID in duplicate detection.
4. When a stable bank transaction ID is unavailable, generate a SHA-256 fingerprint from normalized transaction date, amount, description, and payment method.
5. Scope duplicate detection to the user. Do not deduplicate transactions across different users.
6. For each valid, non-duplicate transaction, create the expense and its import-tracking record in the same database transaction.
7. Duplicate and invalid rows must not create expenses.
8. Update the import job's row counts and status.
9. Make processing idempotent so that retrying a message does not create duplicate expenses.
10. Acknowledge an SQS message only after successful processing or after a failure has been deliberately handled as a terminal outcome.
11. Do not expose raw sensitive financial information in logs or error summaries.

**Known limitation:** Two legitimate transactions with identical date, amount, description, and payment method may be treated as duplicates when no stable bank transaction ID exists. This limitation must be documented and tested.

### 4.8 Database Integrity and Deletion Rules

- Every user-owned record must be associated with the authenticated user.
- All database queries that access user data must enforce ownership.
- An expense cannot reference a category owned by another user.
- An import job cannot reference another user's transactions or expenses.
- Category deletion must be restricted while expenses or budgets reference it, unless an explicit reassignment or deletion policy is implemented.
- Expense deletion and imported-transaction history must be handled consistently to avoid unexpected re-imports.
- Deleting a database record must not be assumed to delete its corresponding S3 object.
- Monetary calculations must use decimal-safe database types rather than floating-point storage.
- Budget usage is calculated from the user's expenses for the relevant month and, when applicable, category.

## 5. Application Architecture

The intended request and processing flow is:

1. The user's browser sends requests to the Flask application on EC2.
2. Flask authenticates the user and performs application-level validation.
3. Flask reads and writes application records in RDS PostgreSQL.
4. Receipt files and original CSV uploads are stored in a private S3 bucket.
5. A CSV upload creates an import job and sends a message to SQS.
6. A separate Python worker process on EC2 receives the SQS message and processes the CSV.
7. The worker writes valid imported transactions and corresponding expenses to RDS.
8. Flask reads import-job status and presents the result to the user.
9. Application and worker logs are sent to CloudWatch.
10. SNS provides configured notifications, and AWS Budgets monitors spending.

The exact message format, API routes, configuration names, and database migrations must be agreed before their implementation diverges between team members.

## 6. Integration Contracts

### 6.1 General Rules

- Use a consistent naming convention across the application.
- Keep credentials and environment-specific configuration outside source code.
- Validate inputs on the backend even when frontend validation exists.
- Return consistent success and error responses.
- Never trust a user ID supplied by the browser without checking the authenticated session.
- Use database transactions for operations that must succeed or fail together.
- Document changes to shared interfaces before merging them.

### 6.2 API Contract

The following is the proposed minimum API surface. Exact paths and response schemas must be finalized before implementation.

| Feature | Proposed operations |
|---|---|
| Authentication | Register, login, logout, current-user details |
| Expenses | List, create, retrieve, update, delete |
| Categories | List, create, update, delete |
| Receipts | Upload and securely access a user's receipt |
| CSV imports | Upload CSV, start import, list jobs, retrieve job status |
| Budgets | List, create, update, delete |
| Dashboard | Retrieve spending summaries and category breakdowns |
| Reports | Retrieve date-filtered spending and budget reports |

Every protected endpoint must verify authentication and ownership. Error responses must not reveal passwords, secrets, database connection strings, or another user's records.

### 6.3 CSV Import Contract

The upload and processing flow must follow this sequence:

1. Flask validates the upload request and stores the CSV in S3.
2. Flask creates an `import_jobs` record with status `queued`.
3. Flask sends a message to SQS containing the minimum information required to locate the job and file, such as `import_job_id`, `user_id`, and `s3_object_key`.
4. The worker retrieves the message and verifies that the job and file correspond to the same user.
5. The worker updates the job status to `processing`.
6. The worker validates and processes rows, using database constraints and transactions to protect against duplicate processing.
7. The worker records counts and sets the job to `completed` or `failed`.
8. The worker acknowledges the SQS message only after the processing outcome is safely recorded.

If an SQS message is retried, the worker must not duplicate expenses. A partially processed job must be recoverable without silently losing transactions.

### 6.4 Configuration Contract

- Application configuration must be read from environment variables or AWS Systems Manager Parameter Store.
- Sensitive values must use `SecureString` parameters where appropriate.
- Parameter names must be agreed by both team members and documented without exposing parameter values.
- EC2 must access AWS services through an attached IAM role.
- No AWS access keys, database passwords, or other secrets may be committed to GitHub.
- The same configuration names must be used by Flask and the worker where they share settings.

## 7. AWS Infrastructure and Security

### 7.1 Required Services

- Amazon EC2 for the Flask application and separate Python worker.
- Amazon VPC with appropriate public and private subnets, routing, and security groups.
- Amazon RDS for PostgreSQL in private subnets.
- Amazon S3 for receipt and CSV storage.
- Amazon SQS for asynchronous CSV import processing.
- AWS Systems Manager Parameter Store for configuration and secrets.
- Amazon SNS for notifications.
- Amazon CloudWatch for logs, metrics, and at least one meaningful alarm.
- AWS Budgets for cost monitoring and budget notifications.

### 7.2 Networking

- EC2 will use a public subnet if required for the agreed access method.
- RDS must remain in private subnets and must not be publicly accessible.
- Configure route tables and an Internet Gateway only as required.
- Security groups must allow only the necessary traffic.
- PostgreSQL access must be limited to the application/worker security group on the required database port.
- Do not expose the database directly to the public internet.
- Avoid NAT Gateways unless a documented requirement justifies their cost; consider alternatives before deployment.

### 7.3 IAM and Secrets

- Use an EC2 instance profile and IAM role rather than hardcoded AWS access keys.
- Apply least privilege to S3, SQS, SNS, Parameter Store, and CloudWatch permissions.
- Do not use unrestricted administrator permissions for the running application.
- Keep S3 buckets private and enable appropriate public-access blocks.
- Do not commit `.env` files or secrets.
- Use HTTPS where applicable and avoid placing secrets in URLs or logs.

### 7.4 Cost Controls

- Check current AWS pricing and the account's available credits before creating resources.
- Confirm the AWS Free Plan's current service restrictions and eligibility.
- Use only one agreed AWS account for integrated project infrastructure.
- Do not assume credits in separate accounts are transferable.
- Prefer small, appropriate instance sizes and the minimum necessary storage.
- Avoid Multi-AZ RDS, load balancers, NAT Gateways, and other costly resources unless specifically justified.
- Configure an AWS Budget and notification thresholds.
- Check for billable resources after testing and remove unneeded resources during cleanup.

## 8. Team Responsibilities

### 8.1 Maria

Primary ownership:

- Expense frontend and backend CRUD operations.
- Expense database operations.
- Receipt upload and retrieval workflow.
- S3 configuration and private access.
- Least-privilege IAM permissions required for S3.
- Application deployment to EC2, coordinated with Aarya.
- Expense and receipt testing.
- Shared documentation and integration review.

### 8.2 Aarya

Primary ownership:

- Budget frontend and backend APIs.
- CSV upload interface and import APIs.
- Budget database operations.
- Import-job status and reporting.
- SQS queue integration.
- Separate Python worker and CSV processing.
- SNS notification integration.
- RDS configuration and Parameter Store integration.
- Worker logging, monitoring, CloudWatch alarm, and AWS Budget alert configuration.
- CSV, budget, and notification testing.

### 8.3 Shared Responsibilities

Both team members must collaborate on:

- Finalizing the project scope, database schema, and API contract.
- Reviewing VPC, routes, security groups, and database connectivity.
- Agreeing on shared configuration and message formats.
- Reviewing IAM permissions and secret handling.
- Integrating and testing all features.
- Maintaining Git branches and reviewing pull requests.
- Preparing architecture diagrams, documentation, screenshots, demo, and viva.
- Verifying AWS costs and cleaning up resources.

These responsibilities define primary ownership, not exclusive access or permission to make incompatible changes.

## 9. Git and Collaboration Rules

- Work on separate feature or documentation branches.
- Do not commit directly to the shared main branch unless both team members agree.
- Use meaningful commit messages.
- Pull the latest changes before starting work.
- Open pull requests for changes that affect shared interfaces or infrastructure.
- Review changes before merging.
- Never commit credentials, `.env` files, personal data, or production secrets.
- Keep README instructions and project documentation synchronized with actual implementation.
- Tell the other team member before changing database constraints, API formats, queue messages, or configuration names.

## 10. Development and Deployment Phases

| Phase | Deliverable |
|---|---|
| 0. Preparation | Account and cost checks, repository setup, project contract, agreed ownership |
| 1. Contract | Approved database schema, API routes, configuration names, and SQS message format |
| 2. Local application | Working Flask skeleton, authentication, database integration, and initial features |
| 3. AWS networking | VPC, subnets, routing, security groups, and EC2 access |
| 4. Database and secrets | Private RDS connectivity, IAM role, Parameter Store integration |
| 5. File storage | Private S3 receipt and CSV upload workflows |
| 6. Asynchronous processing | SQS queue, separate worker, CSV validation, deduplication, and job status |
| 7. Monitoring and notifications | SNS, CloudWatch logs and alarm, AWS Budget notifications |
| 8. Integration testing | End-to-end functional, security, and failure-recovery tests |
| 9. Submission | Documentation, diagrams, screenshots, demo, and viva preparation |
| 10. Cleanup | Remove unneeded resources and verify remaining costs |

Do not create AWS infrastructure until the team has completed the preparation checks and agreed on the relevant contracts.

## 11. Testing and Acceptance Criteria

### 11.1 Functional Testing

- A user can register, log in, and log out.
- A user can create, view, update, and delete their own expenses.
- A user can manage categories without accessing another user's categories.
- Receipt uploads work and remain private.
- CSV files can be uploaded and processed asynchronously.
- Import-job status and row counts are displayed correctly.
- Duplicate and invalid rows do not create duplicate expenses.
- Retrying a job does not create duplicate expenses.
- Monthly budgets and dashboard totals match the underlying expense records.
- Configured notifications work.

### 11.2 Security Testing

- Unauthenticated requests cannot access protected functionality.
- One user cannot read, modify, or delete another user's records.
- RDS is not publicly accessible.
- S3 objects are not publicly accessible.
- IAM permissions are limited to the required operations.
- No secrets appear in Git history, application responses, or logs.

### 11.3 Reliability Testing

- Invalid CSV files produce understandable errors.
- Worker failures can be diagnosed from logs.
- SQS retries do not duplicate successfully imported expenses.
- Database failures do not leave inconsistent import counts or expense records.
- Import jobs reach a meaningful terminal status when processing succeeds or fails.

### 11.4 Cloud and Submission Testing

- The Flask application is accessible through the agreed deployment method.
- The worker runs separately from the Flask web process.
- EC2 can reach RDS without exposing RDS publicly.
- CloudWatch receives application and worker logs.
- At least one meaningful CloudWatch alarm is configured and tested.
- AWS Budget notifications are configured.
- The architecture and deployed resources are documented accurately.

## 12. Documentation and Final Deliverables

The repository should include:

- `README.md` with setup and run instructions.
- `PROJECT_CONTRACT.md` containing the agreed project specification.
- Database schema or migration files.
- Application and worker source code.
- Dependency files, such as `requirements.txt`.
- `.env.example` with placeholder values only.
- AWS architecture diagram.
- Deployment and configuration instructions.
- Testing evidence and screenshots.
- Known limitations and future improvements.
- A final demonstration plan and viva preparation notes.

Do not document a feature as complete until it has been implemented and tested.

## 13. Known Risks and Decisions Requiring Approval

The following must be resolved before the relevant implementation begins:

- Final database schema and migration strategy.
- Exact API paths and response formats.
- Authentication implementation and session handling.
- Exact CSV column mapping and supported bank statement formats.
- Deduplication behavior when bank transaction IDs are absent.
- Whether category and expense deletion is restricted, reassigned, or handled through a retention policy.
- SQS message schema, retry policy, and handling of permanently failed jobs.
- Receipt access method and S3 object naming convention.
- SNS notification types and recipients.
- Exact AWS resource sizes, region, and cost assumptions.
- Final deployment and application access method.

Any change affecting another component must be discussed before implementation.

## 14. Definition of Done

Expensio is ready for submission when:

1. The agreed features are implemented and integrated.
2. Both team members can explain the architecture and their contributions.
3. Database ownership constraints and application authorization are tested.
4. CSV imports are asynchronous, observable, and safe against duplicate processing.
5. Required AWS services are configured securely.
6. Monitoring and cost notifications are configured.
7. Documentation matches the actual system.
8. A working demonstration has been tested.
9. Unneeded billable resources have been cleaned up.

---

**Approval status**

- [ ] Maria reviewed and approved the database schema.
- [ ] Aarya reviewed and approved the database schema.
- [ ] Both approved the API and SQS integration contracts.
- [ ] Both reviewed the AWS security and cost plan.
- [ ] Both approved the final scope and responsibilities.

**Important:** This document is a proposed contract until both team members review and approve it. Update the approval checklist only after agreement.
