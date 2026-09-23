from __future__ import annotations

import json
import math
import os
import re
import shutil
import zipfile
from pathlib import Path
from urllib.parse import urljoin

import pandas as pd
import requests

from .common import require_coordinate
from .dem import (
    COPDEM_CALCULATED_BASIS,
    COPDEM_MEASUREMENT_BASIS,
    dsm_context,
)
from .local_store import (
    connect_catalog,
    parquet_partition_dir,
    register_parquet_dataset,
    register_source_file,
    sha256_file,
    source_snapshot_path,
    utc_now,
)

CATALOGUE_URL = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
DOWNLOAD_BASE = "https://download.dataspace.copernicus.eu/odata/v1/Products"
TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"

COLLECTION = "CCM"
DATASET_PREFIX = "COP-DEM_GLO-30-DGED/"
PRODUCT_TYPE = "SAR_DGE_30_A4AD"
PROVIDER = "Copernicus Data Space Ecosystem / Copernicus DEM"
PROVIDER_KEY = "COPERNICUS_DEM"
DATASET_KEY = "COP_DEM_GLO30_DGED"
RADIUS_M = 500.0
SOURCE_ATTRIBUTION = (
    "© DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018 "
    "provided under COPERNICUS by the European Union and ESA; all rights reserved"
)


def copdem_grid_id(lat: float, lon: float) -> str:
    require_coordinate(lat, lon)
    if lat >= 90 or lon >= 180:
        raise ValueError("Copernicus DEM gridId requires latitude < 90 and longitude < 180")

    south = math.floor(float(lat))
    west = math.floor(float(lon))
    ns = "N" if south >= 0 else "S"
    ew = "E" if west >= 0 else "W"
    return f"{ns}{abs(south):02d}_{ew}{abs(west):03d}"


def _attributes(product: dict) -> dict:
    out = {}
    for attr in product.get("Attributes") or []:
        name = attr.get("Name")
        if name:
            out[str(name)] = attr.get("Value")
    return out


def _release_key(dataset: str | None) -> tuple[int, int]:
    if not dataset:
        return (-1, -1)
    match = re.search(r"/(\d{4})_(\d+)$", str(dataset))
    if not match:
        return (-1, -1)
    return int(match.group(1)), int(match.group(2))


def normalize_product(product: dict) -> dict:
    attrs = _attributes(product)
    return {
        "id": str(product.get("Id") or ""),
        "name": str(product.get("Name") or ""),
        "grid_id": attrs.get("gridId"),
        "dataset": attrs.get("dataset"),
        "delivery": attrs.get("delivery"),
        "product_type": attrs.get("productType"),
        "s3_path": product.get("S3Path"),
        "content_date": product.get("ContentDate"),
    }


def select_latest_product(products: list[dict], grid_id: str) -> dict:
    candidates = []
    for raw in products:
        p = normalize_product(raw)
        if p["grid_id"] != grid_id:
            continue
        if p["product_type"] != PRODUCT_TYPE:
            continue
        if not str(p["dataset"] or "").startswith(DATASET_PREFIX):
            continue
        if not p["id"]:
            continue
        candidates.append(p)

    if not candidates:
        raise ValueError(f"No GLO-30 DGED product found for grid {grid_id}")

    latest_key = max(_release_key(p["dataset"]) for p in candidates)
    latest = [p for p in candidates if _release_key(p["dataset"]) == latest_key]
    if len(latest) != 1:
        ids = sorted(p["id"] for p in latest)
        raise ValueError(
            f"Ambiguous latest GLO-30 product for {grid_id}: {ids}"
        )
    return latest[0]


def catalogue_search(grid_id: str, session=None) -> dict:
    if not re.fullmatch(r"[NS]\d{2}_[EW]\d{3}", grid_id):
        raise ValueError(f"Invalid Copernicus DEM gridId: {grid_id}")

    s = session or requests.Session()
    filter_expr = (
        "Collection/Name eq 'CCM' and "
        "Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'gridId' "
        f"and att/OData.CSC.StringAttribute/Value eq '{grid_id}') and "
        "Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' "
        f"and att/OData.CSC.StringAttribute/Value eq '{PRODUCT_TYPE}')"
    )
    params = {
        "$filter": filter_expr,
        "$expand": "Attributes",
        "$top": "100",
    }

    products = []
    url = CATALOGUE_URL
    while url:
        response = s.get(url, params=params if url == CATALOGUE_URL else None, timeout=60)
        response.raise_for_status()
        payload = response.json()
        products.extend(payload.get("value") or [])
        next_link = payload.get("@odata.nextLink")
        url = urljoin(CATALOGUE_URL, next_link) if next_link else None
        params = None

    return select_latest_product(products, grid_id)


def product_plan(assets: list[dict], session=None) -> tuple[pd.DataFrame, list[dict]]:
    if not assets:
        raise ValueError("No accepted assets supplied")

    rows = []
    for asset in assets:
        grid_id = copdem_grid_id(float(asset["latitude"]), float(asset["longitude"]))
        rows.append({
            "asset_location_id": asset["asset_location_id"],
            "tenant_key": asset["tenant_key"],
            "external_system": asset["external_system"],
            "external_id": asset["external_id"],
            "latitude": float(asset["latitude"]),
            "longitude": float(asset["longitude"]),
            "grid_id": grid_id,
        })
    asset_grids = pd.DataFrame(rows)

    products = [
        catalogue_search(grid_id, session=session)
        for grid_id in sorted(asset_grids["grid_id"].unique())
    ]
    return asset_grids, products


def cdse_access_token(session=None) -> str:
    direct = os.getenv("CDSE_ACCESS_TOKEN")
    if direct:
        return direct.strip()

    username = os.getenv("CDSE_USERNAME")
    password = os.getenv("CDSE_PASSWORD")
    if not username or not password:
        raise RuntimeError(
            "Set CDSE_ACCESS_TOKEN or CDSE_USERNAME/CDSE_PASSWORD locally. "
            "Do not commit CDSE credentials to Git."
        )

    data = {
        "client_id": "cdse-public",
        "grant_type": "password",
        "username": username,
        "password": password,
    }
    totp = os.getenv("CDSE_TOTP")
    if totp:
        data["totp"] = totp

    s = session or requests.Session()
    response = s.post(TOKEN_URL, data=data, timeout=60)
    if response.status_code >= 400:
        raise RuntimeError(
            f"CDSE token request failed with HTTP {response.status_code}. "
            "Check credentials, 2FA/TOTP, and account registration."
        )
    token = response.json().get("access_token")
    if not token:
        raise RuntimeError("CDSE token response did not contain access_token")
    return str(token)


def _verified_source(root: Path, source_id: str, provider_version: str | None = None):
    sql = """
        SELECT * FROM source_artifact
        WHERE source_id=? AND retrieval_status='COMPLETE'
    """
    params = [source_id]
    if provider_version is not None:
        sql += " AND provider_version=?"
        params.append(provider_version)
    sql += " ORDER BY retrieved_at DESC"

    with connect_catalog(root) as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    for row in rows:
        path = root / row["local_path"]
        if path.exists() and sha256_file(path) == row["sha256"]:
            return dict(row)
    return None


def _safe_filename(name: str, fallback: str) -> str:
    value = Path(name or fallback).name
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value)
    return value or fallback


def download_product_package(
    root: str | Path,
    product: dict,
    *,
    access_token: str,
    session=None,
) -> dict:
    root = Path(root).resolve()
    grid_id = str(product["grid_id"])
    product_id = str(product["id"])
    dataset = str(product["dataset"])
    source_id = f"COPDEM_GLO30_PACKAGE_{grid_id}_{product_id[:12]}"

    cached = _verified_source(root, source_id, dataset)
    if cached is not None:
        return cached

    s = session or requests.Session()
    url = f"{DOWNLOAD_BASE}({product_id})/$value"
    response = s.get(
        url,
        headers={"Authorization": f"Bearer {access_token}"},
        stream=True,
        timeout=180,
        allow_redirects=True,
    )
    if response.status_code in (401, 403):
        raise RuntimeError(
            f"CDSE denied Copernicus DEM download for {grid_id} (HTTP {response.status_code}). "
            "Confirm CCM registration/license acceptance and token validity."
        )
    response.raise_for_status()

    tmp = root / "tmp" / f"copdem_{grid_id}_{product_id[:12]}.zip"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    if tmp.exists():
        tmp.unlink()
    with open(tmp, "wb") as f:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if chunk:
                f.write(chunk)
    if not tmp.exists() or tmp.stat().st_size == 0:
        raise RuntimeError("Copernicus DEM download created an empty product")

    if not zipfile.is_zipfile(tmp):
        tmp.unlink(missing_ok=True)
        raise RuntimeError(
            "Downloaded Copernicus DEM product is not a ZIP archive; "
            "the CDSE delivery format may have changed."
        )

    digest = sha256_file(tmp)
    filename = _safe_filename(
        f"{product.get('name') or grid_id}.zip",
        f"copdem_{grid_id}.zip",
    )
    destination = source_snapshot_path(
        root,
        PROVIDER_KEY,
        DATASET_KEY,
        dataset,
        digest,
        filename,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if sha256_file(destination) != digest:
            raise RuntimeError("Content-addressed Copernicus DEM package has unexpected bytes")
        tmp.unlink()
    else:
        shutil.move(str(tmp), str(destination))

    return register_source_file(
        root,
        source_id=source_id,
        provider=PROVIDER,
        provider_version=dataset,
        artifact_path=destination,
        media_type="application/zip",
        retrieval_status="COMPLETE",
        note=(
            "Official Copernicus DEM GLO-30 DGED product package. "
            "Static DSM; not a current bare-earth elevation survey."
        ),
        request_parameters={
            "collection": COLLECTION,
            "product_type": PRODUCT_TYPE,
            "product_id": product_id,
            "product_name": product.get("name"),
            "grid_id": grid_id,
            "dataset": dataset,
            "delivery": product.get("delivery"),
            "catalogue_content_date": product.get("content_date"),
            "s3_path": product.get("s3_path"),
            "download_url": url,
            "required_attribution": SOURCE_ATTRIBUTION,
        },
    )


def extract_dem_raster(
    root: str | Path,
    package_record: dict,
    *,
    grid_id: str,
    product: dict,
) -> dict:
    root = Path(root).resolve()
    package_path = root / package_record["local_path"]
    product_id = str(product["id"])
    dataset = str(product["dataset"])
    source_id = f"COPDEM_GLO30_DEM_{grid_id}_{product_id[:12]}"

    cached = _verified_source(root, source_id, dataset)
    if cached is not None:
        return cached

    with zipfile.ZipFile(package_path) as z:
        members = [
            m for m in z.namelist()
            if Path(m).name.upper().endswith("_DEM.TIF")
        ]
        if len(members) != 1:
            raise ValueError(
                f"Expected exactly one Copernicus DEM GeoTIFF in package, found {members}"
            )
        member = members[0]
        filename = Path(member).name
        tmp = root / "tmp" / filename
        tmp.parent.mkdir(parents=True, exist_ok=True)
        if tmp.exists():
            tmp.unlink()
        with z.open(member) as src, open(tmp, "wb") as dst:
            shutil.copyfileobj(src, dst)

    digest = sha256_file(tmp)
    destination = source_snapshot_path(
        root,
        PROVIDER_KEY,
        DATASET_KEY,
        dataset,
        digest,
        filename,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if sha256_file(destination) != digest:
            raise RuntimeError("Content-addressed Copernicus DEM raster has unexpected bytes")
        tmp.unlink()
    else:
        shutil.move(str(tmp), str(destination))

    return register_source_file(
        root,
        source_id=source_id,
        provider=PROVIDER,
        provider_version=dataset,
        artifact_path=destination,
        media_type="image/tiff",
        retrieval_status="COMPLETE",
        note="Unmodified DEM GeoTIFF member extracted from registered official GLO-30 DGED package.",
        request_parameters={
            "parent_source_artifact_id": package_record["source_artifact_id"],
            "parent_sha256": package_record["sha256"],
            "zip_member": member,
            "grid_id": grid_id,
            "product_id": product_id,
            "required_attribution": SOURCE_ATTRIBUTION,
        },
    )


def extract_dem_rows(
    root: str | Path,
    asset_grids: pd.DataFrame,
    records: dict[str, dict],
    *,
    radius_m: float = RADIUS_M,
) -> pd.DataFrame:
    root = Path(root).resolve()
    rows = []
    for asset in asset_grids.to_dict(orient="records"):
        bundle = records[asset["grid_id"]]
        raster_record = bundle["dem"]
        raster_path = root / raster_record["local_path"]
        ctx = dsm_context(
            raster_path,
            asset["latitude"],
            asset["longitude"],
            radius_m=radius_m,
        )
        rows.append({
            **asset,
            "elevation_dsm_m": ctx["point_elevation_m"],
            f"dsm_local_median_{int(radius_m)}m_m": ctx["local_median_m"],
            f"dsm_relative_elevation_{int(radius_m)}m_m": ctx["relative_elevation_m"],
            f"dsm_local_relief_p90_p10_{int(radius_m)}m_m": ctx["local_relief_p90_p10_m"],
            f"dsm_valid_fraction_{int(radius_m)}m": ctx["valid_fraction"],
            "context_quality_flag": ctx["quality_flag"],
            "context_null_reason": ctx["null_reason"],
            "dem_source_artifact_id": raster_record["source_artifact_id"],
            "package_source_artifact_id": bundle["package"]["source_artifact_id"],
            "dataset": bundle["product"]["dataset"],
            "product_id": bundle["product"]["id"],
        })
    return pd.DataFrame(rows).sort_values(
        ["tenant_key", "external_system", "external_id"]
    ).reset_index(drop=True)


def write_normalized_dem_parquet(
    root: str | Path,
    frame: pd.DataFrame,
    *,
    run_id: str,
) -> Path:
    directory = parquet_partition_dir(
        root,
        layer="normalized",
        dataset="copdem_glo30_asset_context",
        partitions={"radius_m": int(RADIUS_M)},
    )
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"part-{run_id}.parquet"
    frame.to_parquet(path, index=False)
    register_parquet_dataset(
        root,
        dataset_name="copdem_glo30_asset_context",
        layer="normalized",
        parquet_path=path,
        partition_spec={"radius_m": int(RADIUS_M)},
        row_count=len(frame),
        run_id=run_id,
    )
    return path


def insert_dem_indicators(
    root: str | Path,
    frame: pd.DataFrame,
    *,
    run_id: str,
    radius_m: float = RADIUS_M,
) -> int:
    radius = int(radius_m)
    specs = [
        ("elevation_dsm_m", "SOURCE", COPDEM_MEASUREMENT_BASIS, "OK"),
        (
            f"dsm_relative_elevation_{radius}m_m",
            "CALCULATED",
            COPDEM_CALCULATED_BASIS,
            "CONTEXT",
        ),
        (
            f"dsm_local_relief_p90_p10_{radius}m_m",
            "CALCULATED",
            COPDEM_CALCULATED_BASIS,
            "CONTEXT",
        ),
    ]

    count = 0
    with connect_catalog(root) as conn:
        for row in frame.to_dict(orient="records"):
            for indicator_id, value_class, basis, quality_mode in specs:
                value = row.get(indicator_id)
                if pd.isna(value):
                    value = None
                if quality_mode == "OK":
                    quality = "OK" if value is not None else "SOURCE_NODATA"
                    null_reason = None if value is not None else "SOURCE_NODATA"
                else:
                    quality = "OK" if value is not None else row["context_quality_flag"]
                    null_reason = None if value is not None else row["context_null_reason"]

                cur = conn.execute(
                    """
                    INSERT INTO asset_indicator(
                        tenant_key,asset_location_id,indicator_id,value_numeric,value_text,
                        unit,value_class,measurement_basis,source_artifact_id,method_version,
                        period_start,period_end,quality_flag,null_reason,run_id,calculated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        row["tenant_key"],
                        row["asset_location_id"],
                        indicator_id,
                        None if value is None else float(value),
                        None,
                        "m",
                        value_class,
                        basis,
                        row["dem_source_artifact_id"],
                        "COPDEM_GLO30_CONTEXT_0.1",
                        None,
                        None,
                        quality,
                        null_reason,
                        run_id,
                        utc_now(),
                    ),
                )
                indicator_pk = cur.lastrowid
                conn.executemany(
                    """
                    INSERT INTO asset_indicator_source(
                        asset_indicator_id,source_artifact_id,source_role
                    ) VALUES(?,?,?)
                    """,
                    [
                        (
                            indicator_pk,
                            row["dem_source_artifact_id"],
                            "DEM_RASTER",
                        ),
                        (
                            indicator_pk,
                            row["package_source_artifact_id"],
                            "SOURCE_PACKAGE",
                        ),
                    ],
                )
                count += 1
        conn.commit()
    return count
