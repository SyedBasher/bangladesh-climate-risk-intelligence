from __future__ import annotations

import hashlib
import json
import shutil
import time
from datetime import date
from pathlib import Path

import pandas as pd
import rasterio

from .chirps import (
    BASELINE_END,
    BASELINE_START,
    MEASUREMENT_BASIS,
    SOURCE_VINTAGE,
    daily_cog_url,
    daterange,
    expected_days,
    summarize_daily_rainfall,
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

PROVIDER = "UCSB Climate Hazards Center"
PROVIDER_KEY = "UCSB_CHC"
DATASET_KEY = "CHIRPS_V3_FINAL_RNL_SOURCE_SUBSET"
PROVIDER_VERSION = "CHIRPS_v3.0_final_rnl_0.05deg"
BASELINE_DEPENDENT = {
    "r95p_mm",
    "r95p_share_pct",
    "r95p_days",
    "r95_threshold_mm",
}


def asset_signature(assets: list[dict]) -> str:
    payload = [
        {
            "asset_location_id": str(a["asset_location_id"]),
            "latitude": round(float(a["latitude"]), 8),
            "longitude": round(float(a["longitude"]), 8),
        }
        for a in sorted(assets, key=lambda x: str(x["asset_location_id"]))
    ]
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def source_subset_id(year: int, assets: list[dict]) -> str:
    return f"CHIRPS_V3_FINAL_RNL_SUBSET_{int(year)}_{asset_signature(assets)[:16]}"


def year_urls(year: int) -> list[dict]:
    start = date(int(year), 1, 1)
    end = date(int(year), 12, 31)
    return [
        {"date": d.isoformat(), "url": daily_cog_url(d)}
        for d in daterange(start, end)
    ]


def _verified_registered_subset(root: Path, source_id: str):
    with connect_catalog(root) as conn:
        rows = conn.execute(
            """
            SELECT * FROM source_artifact
            WHERE source_id=? AND provider_version=? AND retrieval_status='COMPLETE'
            ORDER BY retrieved_at DESC
            """,
            (source_id, PROVIDER_VERSION),
        ).fetchall()
    for row in rows:
        path = root / row["local_path"]
        if path.exists() and sha256_file(path) == row["sha256"]:
            return dict(row)
    return None


def _sample_remote_cog(url: str, assets: list[dict]) -> list[dict]:
    vsi = f"/vsicurl/{url}"
    env_opts = {
        "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
        "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".cog",
    }
    with rasterio.Env(**env_opts):
        with rasterio.open(vsi) as ds:
            coords = [(float(a["longitude"]), float(a["latitude"])) for a in assets]
            sampled = list(ds.sample(coords, masked=True))
            out = []
            for asset, arr in zip(assets, sampled):
                try:
                    masked = bool(arr.mask[0])
                except Exception:
                    masked = False
                rain = None if masked else float(arr[0])
                if rain is not None and (rain < 0 or not pd.notna(rain)):
                    rain = None
                row, col = ds.index(float(asset["longitude"]), float(asset["latitude"]))
                x, y = ds.xy(row, col)
                out.append({
                    "asset_location_id": asset["asset_location_id"],
                    "tenant_key": asset["tenant_key"],
                    "external_system": asset["external_system"],
                    "external_id": asset["external_id"],
                    "site_identity_grade": asset["site_identity_grade"],
                    "asset_latitude": float(asset["latitude"]),
                    "asset_longitude": float(asset["longitude"]),
                    "grid_row": int(row),
                    "grid_col": int(col),
                    "grid_latitude": float(y),
                    "grid_longitude": float(x),
                    "rain_mm": rain,
                })
            return out


def extract_year_source_subset(
    root: str | Path,
    assets: list[dict],
    year: int,
    *,
    retries: int = 3,
    retry_wait_s: float = 2.0,
) -> tuple[dict, pd.DataFrame]:
    root = Path(root).resolve()
    if not assets:
        raise ValueError("No assets supplied")

    sid = source_subset_id(year, assets)
    cached = _verified_registered_subset(root, sid)
    if cached is not None:
        return cached, pd.read_parquet(root / cached["local_path"])

    rows = []
    remote_manifest = year_urls(year)
    for item in remote_manifest:
        last_error = None
        for attempt in range(1, retries + 1):
            try:
                values = _sample_remote_cog(item["url"], assets)
                for value in values:
                    value["date"] = item["date"]
                    value["source_url"] = item["url"]
                    rows.append(value)
                last_error = None
                break
            except Exception as e:
                last_error = e
                if attempt < retries:
                    time.sleep(retry_wait_s * attempt)
        if last_error is not None:
            raise RuntimeError(
                f"CHIRPS COG extraction failed for {item['date']} after {retries} attempts: {last_error}"
            )

    frame = pd.DataFrame(rows)
    expected = expected_days(year, year) * len(assets)
    if len(frame) != expected:
        raise ValueError(f"Unexpected CHIRPS source-subset row count: {len(frame)}, expected {expected}")
    if frame["rain_mm"].isna().any():
        bad = int(frame["rain_mm"].isna().sum())
        raise ValueError(f"CHIRPS source subset contains {bad} missing rainfall values")

    tmp = root / "tmp" / f"chirps_v3_final_rnl_source_subset_{year}_{asset_signature(assets)[:16]}.parquet"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(tmp, index=False)
    digest = sha256_file(tmp)
    destination = source_snapshot_path(
        root,
        PROVIDER_KEY,
        DATASET_KEY,
        PROVIDER_VERSION,
        digest,
        tmp.name,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if sha256_file(destination) != digest:
            raise RuntimeError("Existing CHIRPS content-addressed subset has unexpected bytes")
        tmp.unlink()
    else:
        shutil.move(str(tmp), str(destination))

    record = register_source_file(
        root,
        source_id=sid,
        provider=PROVIDER,
        provider_version=PROVIDER_VERSION,
        artifact_path=destination,
        media_type="application/vnd.apache.parquet",
        valid_time_start=f"{year}-01-01",
        valid_time_end=f"{year}-12-31",
        retrieval_status="COMPLETE",
        note=(
            "Immutable source-subset snapshot: untransformed CHIRPS v3 final RNL daily "
            "0.05-degree grid-cell rainfall values streamed from official COGs. "
            "This is not a mirror of the full global source archive."
        ),
        request_parameters={
            "artifact_scope": "SOURCE_SUBSET",
            "product": SOURCE_VINTAGE,
            "spatial_resolution_deg": 0.05,
            "daily_disaggregation": "ERA5_REANALYSIS_BASED",
            "asset_signature": asset_signature(assets),
            "year": int(year),
            "remote_sources": remote_manifest,
        },
    )
    return record, frame


def load_year_source_subset(
    root: str | Path,
    assets: list[dict],
    year: int,
) -> tuple[dict, pd.DataFrame]:
    root = Path(root).resolve()
    sid = source_subset_id(year, assets)
    record = _verified_registered_subset(root, sid)
    if record is None:
        raise FileNotFoundError(
            f"No verified CHIRPS source-subset snapshot for year {year} and current asset signature"
        )
    return record, pd.read_parquet(root / record["local_path"])


def required_years(target_year: int, baseline_start: int = BASELINE_START, baseline_end: int = BASELINE_END):
    years = list(range(int(baseline_start), int(baseline_end) + 1))
    if int(target_year) not in years:
        years.append(int(target_year))
    return sorted(years)


def build_asset_metrics(
    root: str | Path,
    assets: list[dict],
    target_year: int,
    *,
    baseline_start: int = BASELINE_START,
    baseline_end: int = BASELINE_END,
) -> tuple[pd.DataFrame, dict[int, dict]]:
    if baseline_start <= int(target_year) <= baseline_end:
        raise ValueError(
            "Target year lies inside the percentile baseline. Bootstrap treatment is not yet "
            "implemented for in-base R95p production calculations."
        )

    source_records = {}
    frames = []
    for year in required_years(target_year, baseline_start, baseline_end):
        record, frame = load_year_source_subset(root, assets, year)
        source_records[year] = record
        frames.append(frame)

    daily = pd.concat(frames, ignore_index=True)
    rows = []
    for asset in assets:
        x = daily[daily["asset_location_id"] == asset["asset_location_id"]][["date", "rain_mm"]]
        results = summarize_daily_rainfall(
            x,
            int(target_year),
            baseline_start=int(baseline_start),
            baseline_end=int(baseline_end),
            require_complete=True,
        )
        for result in results:
            rows.append({
                "tenant_key": asset["tenant_key"],
                "asset_location_id": asset["asset_location_id"],
                "external_id": asset["external_id"],
                "site_identity_grade": asset["site_identity_grade"],
                "indicator_id": result.indicator_id,
                "value": result.value,
                "unit": result.unit,
                "value_class": result.value_class,
                "measurement_basis": result.measurement_basis,
                "method_version": result.method_version,
                "quality_flag": result.quality_flag,
                "target_year": int(target_year),
                "baseline_start": int(baseline_start),
                "baseline_end": int(baseline_end),
            })
    return pd.DataFrame(rows), source_records


def write_indicator_parquet(
    root: str | Path,
    frame: pd.DataFrame,
    *,
    target_year: int,
    run_id: str,
) -> Path:
    directory = parquet_partition_dir(
        root,
        layer="indicators",
        dataset="chirps_rainfall_extremes",
        partitions={"year": int(target_year), "version": "v3_final_rnl"},
    )
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"part-{run_id}.parquet"
    frame.to_parquet(path, index=False)
    register_parquet_dataset(
        root,
        dataset_name="chirps_rainfall_extremes",
        layer="indicators",
        parquet_path=path,
        partition_spec={"year": int(target_year), "version": "v3_final_rnl"},
        row_count=len(frame),
        run_id=run_id,
    )
    return path


def insert_rainfall_indicators(
    root: str | Path,
    frame: pd.DataFrame,
    source_records: dict[int, dict],
    *,
    target_year: int,
    baseline_start: int,
    baseline_end: int,
    run_id: str,
) -> int:
    target_source = source_records[int(target_year)]["source_artifact_id"]
    baseline_sources = [
        source_records[y]["source_artifact_id"]
        for y in range(int(baseline_start), int(baseline_end) + 1)
    ]

    count = 0
    with connect_catalog(root) as conn:
        for row in frame.to_dict(orient="records"):
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
                    row["indicator_id"],
                    float(row["value"]),
                    None,
                    row["unit"],
                    row["value_class"],
                    row["measurement_basis"],
                    target_source,
                    row["method_version"],
                    f"{int(target_year)}-01-01",
                    f"{int(target_year)}-12-31",
                    row["quality_flag"],
                    None,
                    run_id,
                    utc_now(),
                ),
            )
            indicator_pk = cur.lastrowid
            conn.execute(
                """
                INSERT INTO asset_indicator_source(
                    asset_indicator_id,source_artifact_id,source_role
                ) VALUES(?,?,?)
                """,
                (indicator_pk, target_source, "TARGET_SERIES"),
            )
            if row["indicator_id"] in BASELINE_DEPENDENT:
                conn.executemany(
                    """
                    INSERT INTO asset_indicator_source(
                        asset_indicator_id,source_artifact_id,source_role
                    ) VALUES(?,?,?)
                    """,
                    [(indicator_pk, sid, "BASELINE_SERIES") for sid in baseline_sources],
                )
            count += 1
        conn.commit()
    return count
