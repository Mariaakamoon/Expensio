\# Expensio



Expensio is a cloud-based expense tracking and reporting application built with Flask, PostgreSQL, and AWS. It is designed to help users record expenses, organize spending, manage receipts, and support future budget and CSV-import features.



\## Features



\- Add, view, update, and delete expenses.

\- Organize expenses by category.

\- Store receipt files privately in Amazon S3.

\- Use PostgreSQL for structured application data.

\- Planned: budgets, CSV imports, background processing with Amazon SQS, and notifications with Amazon SNS.

## CSV import

The dashboard supports CSV preview and background import through the existing
private S3 bucket and SQS queue. The worker writes imported transactions to the
same `expenses` and `imported_transactions` tables used by the application.

Required environment variables:

- `DATABASE_URL`: PostgreSQL/RDS connection string.
- `S3_RECEIPTS_BUCKET`: existing private bucket used for receipts and CSV files.
- `SQS_CSV_IMPORT_QUEUE_URL`: existing CSV import SQS queue URL.
- `AWS_REGION`: AWS region for the configured resources.

Optional:

- `SNS_IMPORT_TOPIC_ARN`: an existing SNS topic ARN. When set, the worker
  publishes a small completion/failure event containing only the job ID,
  status, and row counts. SNS errors do not undo a successful database import.

Do not put AWS credentials in `.env`. Use an AWS profile locally or an IAM role
on the deployed application and worker.

### Local development

In PowerShell:

```powershell
Copy-Item .env.example .env
# Edit .env with non-secret local configuration.
& .\.venv\Scripts\python.exe -m pytest tests\test_app.py tests\test_worker.py tests\test_csv_routes.py -q
& .\.venv\Scripts\python.exe app.py
```

Run the worker in a second PowerShell window:

```powershell
& .\.venv\Scripts\python.exe worker.py
```

The website is available at `http://127.0.0.1:5001/`. The worker must be
running and have network access to the same database, S3 bucket, and SQS
queue for a real import.

### AWS deployment and operations

Deploy the Flask application and `worker.py` separately. The worker should run
as a supervised EC2 service, container, or other persistent compute workload,
not on a developer's personal computer. The application role needs only the
existing bucket put access and SQS send access. The worker role needs object
read access, SQS receive/delete access, database connectivity, and optional SNS
publish access to the configured topic. Keep the S3 bucket private and use the
queue's existing visibility timeout and redrive/DLQ policy.

If the queue is owned by a different AWS account, the queue-owning account
must allow the worker principal in its SQS resource policy. The producer
principal also needs `sqs:SendMessage`. Do not grant `sqs:*`; replace the
principal below with the actual Aarya worker role or IAM user:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowExpensioWorker",
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam::<worker-account-id>:role/<worker-role-name>"
      },
      "Action": [
        "sqs:ReceiveMessage",
        "sqs:DeleteMessage",
        "sqs:ChangeMessageVisibility",
        "sqs:GetQueueAttributes"
      ],
      "Resource": "arn:aws:sqs:ap-south-1:275695104289:expensio-csv-import"
    }
  ]
}
```

The worker's identity policy must allow the same actions, and its S3 policy
must allow `s3:GetObject` for the CSV prefix. The current local identity
`arn:aws:iam::515060545954:user/expensio-app-user` can send messages, but the
verified worker attempt was denied `sqs:ReceiveMessage`; an S3 `HeadObject`
check was also denied with HTTP 403. These permissions must be fixed by the
appropriate AWS account owner before the job can leave `queued`.

CSV objects are stored below `csv-imports/<user-id>/` in the existing bucket.
Apply the team's retention/lifecycle policy to that prefix; this application
does not delete an object after a successful import so that operations can
audit or retain the source file.

To verify a real import, upload a small CSV in the dashboard, note the job ID,
check the SQS message count and worker logs, then refresh the status until it
is `completed`. Confirm the expense list and `expenses`/
`imported_transactions` records in PostgreSQL. If SNS is configured, inspect
the topic's existing subscription delivery and CloudWatch/SNS delivery
metrics; a successful `Publish` call alone does not prove a subscriber
received the notification.

### Deployment templates

The `deployment/` directory contains local, non-secret templates for the
approved EC2 deployment:

- `deployment/expensio.env.example` targets the confirmed private RDS
  endpoint and existing S3/SQS resources. Copy it to
  `/etc/expensio/expensio.env` on EC2 and replace only the database
  placeholders through the approved secret-storage process.
- `deployment/expensio.service` runs Flask through Gunicorn. Replace the
  placeholder Linux user after inspecting the existing EC2 instance. This is
  a Flask service template only; it intentionally does not create or change
  Aarya's worker service.

Before installing the service, inspect the EC2 instance and confirm that
`127.0.0.1:5001` matches the approved reverse-proxy or SSM access path.

\- Planned: AWS deployment, monitoring, and cost controls.



\## Technology Stack



\- \*\*Frontend:\*\* HTML, CSS, JavaScript, Bootstrap

\- \*\*Backend:\*\* Python, Flask, Flask-SQLAlchemy

\- \*\*Database:\*\* PostgreSQL

\- \*\*Cloud storage:\*\* Amazon S3

\- \*\*AWS SDK:\*\* Boto3

\- \*\*Planned AWS services:\*\* EC2, RDS, SQS, SNS, CloudWatch, and Systems Manager Parameter Store



\## Prerequisites



\- Python installed

\- PostgreSQL installed and running

\- Git installed

\- An AWS account for testing receipt storage in S3



\## Local Setup — Windows PowerShell



\### 1. Clone the repository



```powershell

git clone https://github.com/Mariaakamoon/Expensio.git

cd Expensio

```



\### 2. Create and activate a virtual environment



```powershell

python -m venv .venv

.\\.venv\\Scripts\\Activate.ps1

```



\### 3. Install dependencies



```powershell

python -m pip install -r requirements.txt

```



\### 4. Configure environment variables



Copy the example configuration:



```powershell

Copy-Item .env.example .env

notepad .env

```



Update `DATABASE\_URL` with your local PostgreSQL username, password, host, port, and database name. Keep real credentials in `.env`; never commit them to Git.



Set `AWS\_REGION` and `S3\_RECEIPTS\_BUCKET` to the region and private bucket used for receipt storage.



\### 5. Prepare PostgreSQL



Create a PostgreSQL database and a database user with the necessary permissions. Ensure the connection details match `DATABASE\_URL` in `.env`.



\### 6. Start the application



```powershell

python app.py

```



Open `http://127.0.0.1:5001` in your browser.



The health endpoint is available at:



`http://127.0.0.1:5001/health`



\## Receipt Storage



Receipt uploads require a configured S3 bucket and valid AWS credentials. On AWS, the application should use an attached IAM role with only the permissions it needs. The receipt bucket should remain private.



Do not place AWS access keys or database passwords in source code or commit them to Git.



\## Project Files



\- `app.py` — Flask application and API routes

\- `models.py` — SQLAlchemy database models

\- `templates/` — HTML templates

\- `requirements.txt` — Python dependencies

\- `.env.example` — Example environment configuration without real credentials

\- `DATABASE\_AND\_CSV\_CONTRACT.md` — Database and CSV-import integration contract



\## Development Status



Expensio is under active development. Some planned features and AWS deployment steps may not yet be implemented. Verify the current code before treating a planned feature as complete.
