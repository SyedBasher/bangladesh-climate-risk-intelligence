from __future__ import annotations

import csv
import uuid
from pathlib import Path

from .common import require_coordinate
from .local_store import connect_catalog, utc_now

SITE_GRADES = {
    "EXACT_SITE", "PROBABLE_SITE", "LOCALITY_ONLY",
    "AMBIGUOUS", "NO_MATCH", "REJECTED_ADMIN_MISMATCH",
}
COORDINATE_STATES = {"RESOLVED", "PENDING", "REJECTED"}

REQUIRED_COLUMNS = {
    "external_system", "external_id", "asset_type",
    "latitude", "longitude", "coordinate_source",
    "site_identity_grade", "coordinate_status",
}


def _none(value):
    if value is None:
        return None
    value = str(value).strip()
    return value if value else None


def import_asset_rows(root: str | Path, rows: list[dict], tenant_key: str = "INTERNAL") -> dict:
    inserted = 0
    existing = 0
    rejected = []

    with connect_catalog(root) as conn:
        for i, row in enumerate(rows, start=1):
            missing = REQUIRED_COLUMNS - set(row)
            if missing:
                rejected.append({"row": i, "reason": f"missing columns: {sorted(missing)}"})
                continue
            try:
                lat = float(row["latitude"])
                lon = float(row["longitude"])
                require_coordinate(lat, lon)
                grade = str(row["site_identity_grade"]).strip()
                state = str(row["coordinate_status"]).strip()
                if grade not in SITE_GRADES:
                    raise ValueError(f"unsupported site_identity_grade: {grade}")
                if state not in COORDINATE_STATES:
                    raise ValueError(f"unsupported coordinate_status: {state}")
                precision = _none(row.get("coordinate_precision_m"))
                precision = None if precision is None else float(precision)
                if precision is not None and precision < 0:
                    raise ValueError("coordinate_precision_m cannot be negative")
            except Exception as e:
                rejected.append({"row": i, "reason": str(e)})
                continue

            external_system = str(row["external_system"]).strip()
            external_id = str(row["external_id"]).strip()
            valid_from = _none(row.get("valid_from"))

            found = conn.execute(
                """
                SELECT asset_location_id
                FROM asset_location
                WHERE tenant_key=? AND external_system=? AND external_id=?
                  AND ((valid_from IS NULL AND ? IS NULL) OR valid_from=?)
                """,
                (tenant_key, external_system, external_id, valid_from, valid_from),
            ).fetchone()
            if found:
                existing += 1
                continue

            asset_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO asset_location(
                    asset_location_id,tenant_key,external_system,external_id,asset_type,
                    latitude,longitude,coordinate_source,coordinate_precision_m,
                    site_identity_grade,coordinate_status,valid_from,valid_to,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    asset_id, tenant_key, external_system, external_id,
                    str(row["asset_type"]).strip(),
                    lat, lon, str(row["coordinate_source"]).strip(), precision,
                    grade, state, valid_from, _none(row.get("valid_to")), utc_now(),
                ),
            )
            inserted += 1
        conn.commit()

    return {"inserted": inserted, "existing": existing, "rejected": rejected}


def import_asset_csv(root: str | Path, csv_path: str | Path, tenant_key: str = "INTERNAL") -> dict:
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    return import_asset_rows(root, rows, tenant_key=tenant_key)


def accepted_assets(root: str | Path, tenant_key: str | None = None) -> list[dict]:
    sql = """
        SELECT asset_location_id,tenant_key,external_system,external_id,asset_type,
               latitude,longitude,coordinate_source,coordinate_precision_m,
               site_identity_grade,coordinate_status
        FROM asset_location
        WHERE site_identity_grade='EXACT_SITE'
          AND coordinate_status='RESOLVED'
          AND (valid_to IS NULL OR valid_to > datetime('now'))
    """
    params = ()
    if tenant_key is not None:
        sql += " AND tenant_key=?"
        params = (tenant_key,)
    sql += " ORDER BY tenant_key, external_system, external_id"
    with connect_catalog(root) as conn:
        return [dict(x) for x in conn.execute(sql, params).fetchall()]


def coarse_climate_assets(root: str | Path, tenant_key: str | None = None) -> list[dict]:
    """Resolved coordinates suitable for coarse gridded climate layers (roughly >=1 km)."""
    sql = """
        SELECT asset_location_id,tenant_key,external_system,external_id,asset_type,
               latitude,longitude,coordinate_source,coordinate_precision_m,
               site_identity_grade,coordinate_status
        FROM asset_location
        WHERE site_identity_grade IN ('EXACT_SITE','PROBABLE_SITE')
          AND coordinate_status='RESOLVED'
          AND (valid_to IS NULL OR valid_to > datetime('now'))
    """
    params = ()
    if tenant_key is not None:
        sql += " AND tenant_key=?"
        params = (tenant_key,)
    sql += " ORDER BY tenant_key, external_system, external_id"
    with connect_catalog(root) as conn:
        return [dict(x) for x in conn.execute(sql, params).fetchall()]
