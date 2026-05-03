import time
import pandas as pd
import numpy as np
from django.db import transaction
from ingestion.models import Store, StoreBrand, StoreType, City, State, Country, Region


# ─────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────

CHUNK_SIZE = 50000  # Process 50,000 rows at a time
BATCH_SIZE = 5000   # Bulk create in smaller batches to avoid memory issues


# ─────────────────────────────────────────
# HELPER — Normalize a string value
# ─────────────────────────────────────────

def normalize(value):
    if not value or str(value).strip() == '':
        return None
    return str(value).strip().title()


# ─────────────────────────────────────────
# HELPER — Bulk Get or Create Lookup Values
# ─────────────────────────────────────────

def bulk_get_or_create_lookup(model, values):
    values = {v for v in values if v}
    if not values:
        return {}

    # Fetch all existing records in one query
    existing = {
        obj.name.lower(): obj  # Use lowercase for case-insensitive matching
        for obj in model.objects.filter(name__in=values)
    }

    missing = values - set(existing.keys())

    if missing:
        missing_list = list(missing)
        for i in range(0, len(missing_list), BATCH_SIZE):
            batch = missing_list[i:i + BATCH_SIZE]
            model.objects.bulk_create(
                [model(name=v) for v in batch],
                ignore_conflicts=True,
                batch_size=BATCH_SIZE
            )
        newly_fetched = {
            obj.name.lower(): obj
            for obj in model.objects.filter(name__in=missing)
        }
        existing.update(newly_fetched)

    return existing


# ─────────────────────────────────────────
# HELPER — Preload Lookups into Memory
# ─────────────────────────────────────────

def preload_lookups():
    return {
        'store_brands': {obj.name.lower(): obj for obj in StoreBrand.objects.all().only('id', 'name')},
        'store_types':  {obj.name.lower(): obj for obj in StoreType.objects.all().only('id', 'name')},
        'cities':       {obj.name.lower(): obj for obj in City.objects.all().only('id', 'name')},
        'states':       {obj.name.lower(): obj for obj in State.objects.all().only('id', 'name')},
        'countries':    {obj.name.lower(): obj for obj in Country.objects.all().only('id', 'name')},
        'regions':      {obj.name.lower(): obj for obj in Region.objects.all().only('id', 'name')},
    }


# ─────────────────────────────────────────
# HELPER — Vectorized Validation
# ─────────────────────────────────────────

def validate_chunk_vectorized(chunk, seen_store_ids, chunk_index):
    """
    Validates entire chunk using pandas vectorized operations.
    No row-by-row loops — pandas processes entire columns at once in C.
    """
    errors      = []
    failed_mask = pd.Series(False, index=chunk.index)

    row_numbers = pd.Series(
        range(chunk_index * CHUNK_SIZE + 2, chunk_index * CHUNK_SIZE + 2 + len(chunk)),
        index=chunk.index
    ) # to log the row number in actual csv file

    # ── Check 1: Duplicate store_id across file ──
    dup_global = chunk['store_id'].isin(seen_store_ids)
    for idx in chunk[dup_global].index:
        errors.append({
            'row':    int(row_numbers[idx]),
            'column': 'store_id',
            'reason': f'Duplicate store_id "{chunk.loc[idx, "store_id"]}" found in this file'
        })
    failed_mask |= dup_global

    # ── Check 2: Duplicate store_id within this chunk ──
    dup_within = chunk['store_id'].duplicated(keep='first')
    for idx in chunk[dup_within & ~failed_mask].index:
        errors.append({
            'row':    int(row_numbers[idx]),
            'column': 'store_id',
            'reason': f'Duplicate store_id "{chunk.loc[idx, "store_id"]}" found in this file'
        })
    failed_mask |= dup_within

    # ── Check 3: Required fields ──
    for field in ['store_id', 'name', 'title']:
        empty_mask = chunk[field].str.strip() == ''
        for idx in chunk[empty_mask & ~failed_mask].index:
            errors.append({
                'row':    int(row_numbers[idx]),
                'column': field,
                'reason': f'{field} is required and cannot be empty'
            })
        failed_mask |= empty_mask

    # ── Check 4: Field length limits ──
    for field, max_len in [('store_id', 255), ('store_external_id', 255), ('name', 255), ('title', 255)]:
        if field in chunk.columns:
            long_mask = chunk[field].str.len() > max_len
            for idx in chunk[long_mask & ~failed_mask].index:
                errors.append({
                    'row':    int(row_numbers[idx]),
                    'column': field,
                    'reason': f'{field} exceeds maximum length of {max_len} characters'
                })
            failed_mask |= long_mask

    # ── Check 5: Latitude/Longitude must be numeric ──
    for coord in ['latitude', 'longitude']:
        if coord in chunk.columns:
            non_empty   = chunk[coord].str.strip() != ''
            numeric_col = pd.to_numeric(chunk[coord], errors='coerce')
            invalid     = non_empty & numeric_col.isna()
            for idx in chunk[invalid & ~failed_mask].index:
                errors.append({
                    'row':    int(row_numbers[idx]),
                    'column': coord,
                    'reason': f'{coord} must be a valid number'
                })
            failed_mask |= invalid

    # Add valid store_ids to global seen set
    valid_chunk = chunk[~failed_mask].copy()
    seen_store_ids.update(valid_chunk['store_id'].tolist())

    return valid_chunk, errors, int(failed_mask.sum())


# ─────────────────────────────────────────
# MAIN — Ingest Stores CSV
# ─────────────────────────────────────────

def ingest_stores(file):

    start_time = time.time()

    total_ingested = 0
    total_failed   = 0
    all_errors     = []
    seen_store_ids = set()

    # Preload all lookup data into memory once
    lookups     = preload_lookups()
    new_lookups = {k: set() for k in lookups}

    lookup_models = {
        'store_brands': StoreBrand,
        'store_types':  StoreType,
        'cities':       City,
        'states':       State,
        'countries':    Country,
        'regions':      Region,
    }

    col_to_key = {
        'store_brand': 'store_brands',
        'store_type':  'store_types',
        'city':        'cities',
        'state':       'states',
        'country':     'countries',
        'region':      'regions',
    }

    chunk_iter = pd.read_csv(
        file,
        dtype=str,
        chunksize=CHUNK_SIZE,
        low_memory=False,
        na_filter=False,
        keep_default_na=False
    )

    for chunk_index, chunk in enumerate(chunk_iter):

        chunk.columns = chunk.columns.str.strip()
        chunk = chunk.replace({np.nan: '', 'nan': '', 'None': '', 'null': ''})
        chunk['store_id'] = chunk['store_id'].str.strip()

        # ── Step 1: Vectorized validation ──
        valid_chunk, chunk_errors, failed_count = validate_chunk_vectorized(
            chunk, seen_store_ids, chunk_index
        )
        total_failed  += failed_count
        all_errors.extend(chunk_errors)

        if valid_chunk.empty:
            continue

        # ── Step 2: Normalize lookup columns for entire chunk at once ──
        for col in col_to_key:
            if col in valid_chunk.columns:
                valid_chunk[col] = valid_chunk[col].str.strip().str.title()

        # ── Step 3: Find new lookup values not in memory cache ──
        for col, key in col_to_key.items():
            if col in valid_chunk.columns:
                unique_vals = set(valid_chunk[col].str.lower().unique()) - {''}
                new_lookups[key].update(unique_vals - set(lookups[key].keys()))

        # ── Step 4: Bulk create new lookup values and refresh cache ──
        with transaction.atomic():
            for key, model in lookup_models.items():
                if new_lookups[key]:
                    vals_to_create = {v.title() for v in new_lookups[key]}
                    for i in range(0, len(vals_to_create), BATCH_SIZE):
                        batch = list(vals_to_create)[i:i + BATCH_SIZE]
                        model.objects.bulk_create(
                            [model(name=v) for v in batch],
                            ignore_conflicts=True,
                            batch_size=BATCH_SIZE
                        )
                    for obj in model.objects.filter(name__in=vals_to_create).only('id', 'name'):
                        lookups[key][obj.name.lower()] = obj
                    new_lookups[key].clear()

        # ── Step 5: Build Store objects using itertuples ──
        store_objects = []
        for row in valid_chunk.itertuples(index=False):
            def get_lookup(key, col):
                val = getattr(row, col, '') or ''
                return lookups[key].get(val.lower()) if val.strip() else None

            try:
                lat = float(getattr(row, 'latitude',  0) or 0)
                lon = float(getattr(row, 'longitude', 0) or 0)
            except (ValueError, TypeError):
                lat, lon = 0.0, 0.0

            store_objects.append(Store(
                store_id          = str(row.store_id).strip(),
                store_external_id = str(getattr(row, 'store_external_id', '')).strip()[:255],
                name              = str(row.name).strip()[:255],
                title             = str(row.title).strip()[:255],
                store_brand       = get_lookup('store_brands', 'store_brand'),
                store_type        = get_lookup('store_types',  'store_type'),
                city              = get_lookup('cities',       'city'),
                state             = get_lookup('states',       'state'),
                country           = get_lookup('countries',    'country'),
                region            = get_lookup('regions',      'region'),
                latitude          = lat,
                longitude         = lon,
                is_active         = str(getattr(row, 'is_active', 'true')).strip().lower() not in ['false', '0', 'no'],
            ))

        # ── Step 6: Bulk upsert in batches ──
        if store_objects:
            with transaction.atomic():
                for i in range(0, len(store_objects), BATCH_SIZE):
                    batch = store_objects[i:i + BATCH_SIZE]
                    Store.objects.bulk_create(
                        batch,
                        update_conflicts=True,
                        unique_fields=['store_id'],
                        update_fields=[
                            'store_external_id', 'name', 'title',
                            'store_brand', 'store_type', 'city',
                            'state', 'country', 'region',
                            'latitude', 'longitude', 'is_active', 'modified_on'
                        ],
                        batch_size=BATCH_SIZE
                    )
                    total_ingested += len(batch)

    end_time = time.time()

    return {
        'total_rows': total_ingested + total_failed,
        'ingested':   total_ingested,
        'failed':     total_failed,
        'time_taken': f'{round(end_time - start_time, 2)} seconds',
        'errors':     all_errors
    }


    