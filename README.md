# Infilect Data Ingestion Assignment

A backend service built with Django and PostgreSQL that accepts CSV file uploads, validates every row, and ingests data into a relational database.

---

## Tech Stack

- **Framework** — Django + Django REST Framework
- **Database** — PostgreSQL (via Docker)
- **CSV Processing** — pandas
- **Language** — Python 3.13.5

---

## Project Structure

```
infilect_assignment/
├── manage.py
├── requirements.txt
├── docker-compose.yml
├── infilect_assignment/
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
└── ingestion/
    ├── models.py
    ├── views.py
    ├── urls.py
    └── services/
        ├── store_ingestor.py
        ├── user_ingestor.py
        └── pjp_ingestor.py
```

---

## Setup Instructions

### 1. Clone the repository

```bash
git clone https://github.com/sainiSimran02/data-ingestion.git
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Start PostgreSQL using Docker

```bash
docker-compose up -d
```

### 4. Run migrations

```bash
python manage.py makemigrations
python manage.py migrate
```

### 5. Start the server

```bash
python manage.py runserver
```

Server runs at `http://127.0.0.1:8000/`

---

## API Endpoints

### Upload Stores

```
POST /api/upload/stores/
Content-Type: multipart/form-data
Body: file = stores_master.csv
```

### Upload Users

```
POST /api/upload/users/
Content-Type: multipart/form-data
Body: file = users_master.csv
```

### Upload Store-User Mapping (PJP)

```
POST /api/upload/pjp/
Content-Type: multipart/form-data
Body: file = store_user_mapping.csv
```

### Get Count of different entries in db(Stores, Users, PJP) [Just an add on]

```
POST /api/status/
```

> ⚠️ Important: Upload stores and users before uploading PJP mapping.

---

## CSV File Formats

### stores_master.csv

```
store_id, store_external_id, name, title, store_brand, store_type,
city, state, country, region, latitude, longitude, is_active
```

### users_master.csv

```
username, first_name, last_name, email, user_type,
phone_number, supervisor, is_active
```

### store_user_mapping.csv

```
username, store_id, date, is_active
```

---

## Sample Response

```json
{
  "total_rows": 100,
  "ingested": 94,
  "failed": 6,
  "errors": [
    {
      "row": 7,
      "column": "store_id",
      "reason": "Duplicate store_id \"STR-0004\" found in this file"
    },
    {
      "row": 13,
      "column": "store_id",
      "reason": "store_id is required and cannot be empty"
    }
  ]
}
```

---

## Key Design Decisions

### 1. Failure Policy — Skip bad rows, ingest the rest

When a row fails validation, that row is skipped and recorded in the error report. All valid rows are still ingested.

**Why?**

- In retail operations, CSV files can have hundreds or thousands of rows
- Rejecting the entire file because of a few bad rows wastes time
- The client gets a clear error report and can fix only the bad rows
- Partial ingestion is always better than zero ingestion for large files

### 2. Lookup Table Normalization

Before doing a get-or-create on any lookup value, the value is normalized:

```python
normalized = str(value).strip().title()
```

This means:

- `"mumbai"` → `"Mumbai"`
- `" DELHI "` → `"Delhi"`
- `"new delhi"` → `"New Delhi"`

**Why?**

- The same city uploaded in different cases should not create duplicate records
- Stripping whitespace handles accidental spaces in CSV values
- Title case gives a consistent, clean display format

### 3. Upsert Strategy — update_or_create

Instead of failing on duplicate uploads, we use Django's `update_or_create`:

- If a store/user already exists → update it with new values
- If it doesn't exist → create it

**Why?**

- Clients may re-upload corrected versions of the same file
- Re-uploading should update the data, not throw errors
- Natural keys used: `store_id` for stores, `username` for users

### 4. Supervisor Resolution — Warn, don't reject

If a user's supervisor username is not found in the database:

- The user is still saved without a supervisor
- A warning is returned in the response
- The row is NOT counted as a failure

**Why?**

- A user's core data (username, email, phone) is still valid
- The supervisor field is not critical enough to reject the whole row
- The client can fix supervisor assignments in a follow-up upload

### 5. PJP depends on Stores and Users

PJP rows are strictly rejected if the referenced user or store doesn't exist.

**Why?**

- A store-user mapping without a valid store or user is meaningless
- Unlike supervisor (which is optional context), both FKs are required for the mapping to make sense

---

## Validation Rules

### Stores

| Field     | Rule                            |
| --------- | ------------------------------- |
| store_id  | Required, unique, max 255 chars |
| name      | Required, max 255 chars         |
| title     | Required, max 255 chars         |
| latitude  | Must be a valid number          |
| longitude | Must be a valid number          |

### Users

| Field        | Rule                            |
| ------------ | ------------------------------- |
| username     | Required, unique, max 150 chars |
| email        | Required, valid email format    |
| phone_number | Optional, valid phone format    |
| user_type    | Must be 1, 2, 3, or 7           |

### PJP

| Field               | Rule                                 |
| ------------------- | ------------------------------------ |
| username            | Required, must exist in users table  |
| store_id            | Required, must exist in stores table |
| date                | Optional, must be YYYY-MM-DD format  |
| username + store_id | Combination must be unique           |
