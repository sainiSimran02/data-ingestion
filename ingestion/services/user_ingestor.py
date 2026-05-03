import re
import time
import pandas as pd
from ingestion.models import User


# ─────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────

CHUNK_SIZE = 10000  # Process 10,000 rows at a time


# ─────────────────────────────────────────
# HELPER — Validate Email Format
# ─────────────────────────────────────────

def is_valid_email(email):
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, str(email).strip()))


# ─────────────────────────────────────────
# HELPER — Validate Phone Format
# ─────────────────────────────────────────

def is_valid_phone(phone):
    pattern = r'^\+?[\d\s\-]{7,15}$'
    return bool(re.match(pattern, str(phone).strip()))


# ─────────────────────────────────────────
# HELPER — Validate a Single Row
# ─────────────────────────────────────────

def validate_row(row, row_number):
    errors = []

    # --- Required fields ---
    required_fields = ['username', 'email']
    for field in required_fields:
        if not row.get(field) or str(row[field]).strip() == '':
            errors.append({
                'row': row_number,
                'column': field,
                'reason': f'{field} is required and cannot be empty'
            })

    # --- Email format ---
    email = row.get('email', '')
    if email and not is_valid_email(email):
        errors.append({
            'row': row_number,
            'column': 'email',
            'reason': f'"{email}" is not a valid email address'
        })

    # --- Phone format ---
    phone = row.get('phone_number', '')
    if phone and not is_valid_phone(phone):
        errors.append({
            'row': row_number,
            'column': 'phone_number',
            'reason': f'"{phone}" is not a valid phone number'
        })

    # --- user_type must be 1, 2, 3, or 7 ---
    user_type = row.get('user_type', '1')
    if user_type:
        try:
            if int(user_type) not in [1, 2, 3, 7]:
                errors.append({
                    'row': row_number,
                    'column': 'user_type',
                    'reason': f'user_type must be 1, 2, 3, or 7. Got "{user_type}"'
                })
        except ValueError:
            errors.append({
                'row': row_number,
                'column': 'user_type',
                'reason': f'user_type must be a number. Got "{user_type}"'
            })

    # --- Field length limits ---
    length_limits = {
        'username': 150, 'first_name': 150,
        'last_name': 150, 'email': 254, 'phone_number': 32,
    }
    for field, max_length in length_limits.items():
        value = row.get(field, '')
        if value and len(str(value)) > max_length:
            errors.append({
                'row': row_number,
                'column': field,
                'reason': f'{field} exceeds maximum length of {max_length} characters'
            })

    return errors


# ─────────────────────────────────────────
# MAIN — Ingest Users CSV (Optimized)
# ─────────────────────────────────────────

def ingest_users(file):

    start_time = time.time()  # start timer

    total_ingested = 0
    total_failed   = 0
    all_errors     = []
    all_warnings   = []
    seen_usernames = set()

    chunk_iter = pd.read_csv(file, dtype=str, chunksize=CHUNK_SIZE)

    for chunk_index, chunk in enumerate(chunk_iter):

        chunk.columns = chunk.columns.str.strip()
        chunk = chunk.fillna('')

        valid_rows   = []
        chunk_errors = []

        # ── Step 1: Validate all rows in this chunk ──
        for index, row in chunk.iterrows():
            row_number = chunk_index * CHUNK_SIZE + index + 2
            username   = str(row.get('username', '')).strip()

            if username in seen_usernames:
                chunk_errors.append({
                    'row': row_number,
                    'column': 'username',
                    'reason': f'Duplicate username "{username}" found in this file'
                })
                total_failed += 1
                continue

            seen_usernames.add(username)

            row_errors = validate_row(row, row_number)
            if row_errors:
                chunk_errors.extend(row_errors)
                total_failed += 1
                continue

            valid_rows.append((row_number, row))

        # ── Step 2: Resolve all supervisor FKs in bulk ──
        supervisor_usernames = {
            str(r.get('supervisor', '')).strip()
            for _, r in valid_rows
            if r.get('supervisor') and str(r.get('supervisor')).strip() != ''
        }

        supervisor_map = {
            u.username: u
            for u in User.objects.filter(username__in=supervisor_usernames)
        }

        missing_supervisors = supervisor_usernames - set(supervisor_map.keys())
        for missing in missing_supervisors:
            all_warnings.append({
                'column': 'supervisor',
                'reason': f'Supervisor "{missing}" not found. Affected users saved without supervisor.'
            })

        # ── Step 3: Build User objects in memory ──
        user_objects = []
        for row_number, row in valid_rows:
            username   = str(row.get('username', '')).strip()
            supervisor = supervisor_map.get(str(row.get('supervisor', '')).strip())

            user_objects.append(User(
                username     = username,
                first_name   = str(row.get('first_name', '')).strip(),
                last_name    = str(row.get('last_name',  '')).strip(),
                email        = str(row.get('email',      '')).strip(),
                user_type    = int(row.get('user_type') or 1),
                phone_number = str(row.get('phone_number', '')).strip(),
                supervisor   = supervisor,
                is_active    = str(row.get('is_active', 'true')).strip().lower() != 'false',
            ))

        # ── Step 4: Bulk upsert all users in ONE DB call ──
        if user_objects:
            User.objects.bulk_create(
                user_objects,
                update_conflicts=True,
                unique_fields=['username'],
                update_fields=[
                    'first_name', 'last_name', 'email',
                    'user_type', 'phone_number', 'supervisor',
                    'is_active', 'modified_on'
                ]
            )
            total_ingested += len(user_objects)

        all_errors.extend(chunk_errors)

    end_time = time.time()

    return {
        'total_rows': total_ingested + total_failed,
        'ingested':   total_ingested,
        'failed':     total_failed,
        'time_taken': f'{round(end_time - start_time, 2)} seconds',
        'errors':     all_errors,
        'warnings':   all_warnings
    }