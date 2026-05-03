import time
import pandas as pd
from datetime import datetime
from ingestion.models import User, Store, PermanentJourneyPlan


# ─────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────

CHUNK_SIZE = 10000  # Process 10,000 rows at a time


# ─────────────────────────────────────────
# HELPER — Validate Date Format
# ─────────────────────────────────────────

def is_valid_date(date_str):
    if not date_str or str(date_str).strip() == '':
        return True  # Date is optional
    try:
        datetime.strptime(str(date_str).strip(), '%Y-%m-%d')
        return True
    except ValueError:
        return False


# ─────────────────────────────────────────
# HELPER — Validate a Single Row
# ─────────────────────────────────────────

def validate_row(row, row_number):
    errors = []

    for field in ['username', 'store_id']:
        if not row.get(field) or str(row[field]).strip() == '':
            errors.append({
                'row': row_number,
                'column': field,
                'reason': f'{field} is required and cannot be empty'
            })

    date = row.get('date', '')
    if date and not is_valid_date(date):
        errors.append({
            'row': row_number,
            'column': 'date',
            'reason': f'"{date}" is not a valid date. Expected format: YYYY-MM-DD'
        })

    return errors


# ─────────────────────────────────────────
# MAIN — Ingest PJP CSV (Optimized)
# ─────────────────────────────────────────

def ingest_pjp(file):

    start_time = time.time()  # ← Start timer

    total_ingested = 0
    total_failed   = 0
    all_errors     = []
    seen_mappings  = set()

    chunk_iter = pd.read_csv(file, dtype=str, chunksize=CHUNK_SIZE)

    for chunk_index, chunk in enumerate(chunk_iter):

        chunk.columns = chunk.columns.str.strip()
        chunk = chunk.fillna('')

        valid_rows   = []
        chunk_errors = []

        # ── Step 1: Validate all rows in this chunk ──
        for index, row in chunk.iterrows():
            row_number   = chunk_index * CHUNK_SIZE + index + 2
            username     = str(row.get('username', '')).strip()
            store_id     = str(row.get('store_id', '')).strip()
            mapping_key  = (username, store_id)

            if mapping_key in seen_mappings:
                chunk_errors.append({
                    'row': row_number,
                    'column': 'username + store_id',
                    'reason': f'Duplicate mapping "{username} → {store_id}" found in this file'
                })
                total_failed += 1
                continue

            seen_mappings.add(mapping_key)

            row_errors = validate_row(row, row_number)
            if row_errors:
                chunk_errors.extend(row_errors)
                total_failed += 1
                continue

            valid_rows.append((row_number, row))

        if not valid_rows:
            all_errors.extend(chunk_errors)
            continue

        # ── Step 2: Resolve all User FKs in bulk ──
        usernames = {str(r.get('username', '')).strip() for _, r in valid_rows}
        user_map  = {u.username: u for u in User.objects.filter(username__in=usernames)}

        # ── Step 3: Resolve all Store FKs in bulk ──
        store_ids = {str(r.get('store_id', '')).strip() for _, r in valid_rows}
        store_map = {s.store_id: s for s in Store.objects.filter(store_id__in=store_ids)}

        # ── Step 4: Build PJP objects in memory ──
        pjp_objects = []
        for row_number, row in valid_rows:
            username = str(row.get('username', '')).strip()
            store_id = str(row.get('store_id', '')).strip()

            user = user_map.get(username)
            if not user:
                chunk_errors.append({
                    'row': row_number,
                    'column': 'username',
                    'reason': f'User "{username}" does not exist. Please upload users_master.csv first.'
                })
                total_failed += 1
                continue

            store = store_map.get(store_id)
            if not store:
                chunk_errors.append({
                    'row': row_number,
                    'column': 'store_id',
                    'reason': f'Store "{store_id}" does not exist. Please upload stores_master.csv first.'
                })
                total_failed += 1
                continue

            date_str = str(row.get('date', '')).strip()
            date     = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else None

            pjp_objects.append(PermanentJourneyPlan(
                user      = user,
                store     = store,
                date      = date,
                is_active = str(row.get('is_active', 'true')).strip().lower() != 'false',
            ))

        # ── Step 5: Bulk upsert all PJP rows in ONE DB call ──
        if pjp_objects:
            PermanentJourneyPlan.objects.bulk_create(
                pjp_objects,
                update_conflicts=True,
                unique_fields=['user', 'store'],
                update_fields=['date', 'is_active', 'modified_on']
            )
            total_ingested += len(pjp_objects)

        all_errors.extend(chunk_errors)

    end_time = time.time()  # ← Stop timer

    return {
        'total_rows': total_ingested + total_failed,
        'ingested':   total_ingested,
        'failed':     total_failed,
        'time_taken': f'{round(end_time - start_time, 2)} seconds',
        'errors':     all_errors
    }