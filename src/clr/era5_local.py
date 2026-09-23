from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .local_store import (
    connect_catalog,
    finish_processing_run,
    parquet_partition_dir,
    register_parquet_dataset,
    register_source_file,
    sha256_file,
    source_snapshot_path,
    start_processing_run,
    utc_now,
)

DATASET = "derived-era5-land-daily-statistics"
SOURCE_ID_MAX = "ERA5L_DAILY_MAX"
SOURCE_ID_MIN = "ERA5L_DAILY_MIN"
PROVIDER = "ECMWF_COPERNICUS_CDS"
TIME_ZONE = "utc+06:00"
VARIABLE = "2m_temperature"
VALID_STATS = {"daily_maximum", "daily_minimum"}


def area_from_assets(assets: list[dict], pad_deg: float = 0.1) -> list[float]:
    if not assets:
        raise ValueError("No accepted assets supplied")
    if pad_deg < 0:
        raise ValueError("pad_deg cannot be negative")
    lats = [float(x["latitude"]) for x in assets]
    lons = [float(x["longitude"]) for x in assets]
    return [
        min(90.0, max(lats) + pad_deg),
        max(-180.0, min(lons) - pad_deg),
        max(-90.0, min(lats) - pad_deg),
        min(180.0, max(lons) + pad_deg),
    ]


def daily_request(assets: list[dict], year: int, statistic: str) -> dict:
    if statistic not in VALID_STATS:
        raise ValueError(f"Unsupported daily statistic: {statistic}")
    if not (1950 <= int(year) <= 2100):
        raise ValueError("ERA5-Land year outside supported planning range")
    return {
        "variable": [VARIABLE],
        "year": str(int(year)),
        "month": [f"{m:02d}" for m in range(1, 13)],
        "day": [f"{d:02d}" for d in range(1, 32)],
        "daily_statistic": statistic,
        "time_zone": TIME_ZONE,
        "frequency": "1_hourly",
        "area": area_from_assets(assets),
    }


def request_digest(request: dict) -> str:
    payload = json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def request_plan(assets: list[dict], year: int) -> list[dict]:
    out = []
    for statistic, source_id in (
        ("daily_maximum", SOURCE_ID_MAX),
        ("daily_minimum", SOURCE_ID_MIN),
    ):
        request = daily_request(assets, year, statistic)
        out.append({
            "dataset": DATASET,
            "source_id": source_id,
            "year": int(year),
            "statistic": statistic,
            "request_sha256": request_digest(request),
            "request": request,
        })
    return out


def _provider_version() -> str:
    return "daily_stats_retrieval_" + datetime.now(timezone.utc).strftime("%Y%m%d")


def retrieve_request_to_private_store(
    root: str | Path,
    *,
    source_id: str,
    year: int,
    statistic: str,
    request: dict,
    client=None,
) -> dict:
    root = Path(root).resolve()
    if statistic not in VALID_STATS:
        raise ValueError("Unsupported statistic")
    if request.get("daily_statistic") != statistic:
        raise ValueError("Request/statistic mismatch")

    if client is None:
        try:
            import cdsapi
        except ImportError as e:
            raise RuntimeError(
                "cdsapi is required. Install requirements-local.txt."
            ) from e
        client = cdsapi.Client()

    digest = request_digest(request)
    tmp = root / "tmp" / f"era5land_{year}_{statistic}_{digest[:12]}.zip"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    if tmp.exists():
        tmp.unlink()

    client.retrieve(DATASET, request).download(str(tmp))
    if not tmp.exists() or tmp.stat().st_size == 0:
        raise RuntimeError("CDS retrieval did not create a non-empty artifact")

    artifact_sha = sha256_file(tmp)
    version = _provider_version()
    destination = source_snapshot_path(
        root,
        PROVIDER,
        DATASET,
        version,
        artifact_sha,
        f"era5land_{year}_{statistic}.zip",
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if sha256_file(destination) != artifact_sha:
            raise RuntimeError("Existing content-addressed artifact has unexpected bytes")
        tmp.unlink()
    else:
        shutil.move(str(tmp), str(destination))

    return register_source_file(
        root,
        source_id=source_id,
        provider="Copernicus Climate Data Store / ECMWF",
        provider_version=version,
        artifact_path=destination,
        media_type="application/zip",
        valid_time_start=f"{year}-01-01T00:00:00+06:00",
        valid_time_end=f"{year}-12-31T23:59:59+06:00",
        retrieval_status="COMPLETE",
        note="ERA5-Land post-processed daily statistics; local-day aggregation requested at UTC+06:00.",
        request_parameters={"dataset": DATASET, **request},
    )


def _temperature_variable(ds):
    for name in ("t2m", "2m_temperature"):
        if name in ds.data_vars:
            return name
    for name, var in ds.data_vars.items():
        if str(var.attrs.get("standard_name", "")).lower() == "air_temperature":
            return name
    if len(ds.data_vars) == 1:
        return next(iter(ds.data_vars))
    raise ValueError(f"Could not identify temperature variable among {list(ds.data_vars)}")


def _coord_name(ds, candidates):
    for name in candidates:
        if name in ds.coords or name in ds.dims:
            return name
    raise ValueError(f"Missing coordinate; expected one of {candidates}")


def extract_daily_temperature_zip(
    zip_path: str | Path,
    assets: list[dict],
    *,
    statistic: str,
    source_artifact_id: str,
) -> pd.DataFrame:
    if statistic not in VALID_STATS:
        raise ValueError("Unsupported statistic")
    try:
        import xarray as xr
    except ImportError as e:
        raise RuntimeError("xarray is required. Install requirements-local.txt.") from e

    rows = []
    with tempfile.TemporaryDirectory() as td:
        with zipfile.ZipFile(zip_path) as z:
            members = [m for m in z.namelist() if m.lower().endswith(".nc")]
            if not members:
                raise ValueError("ERA5-Land daily archive contains no NetCDF file")
            for member in members:
                z.extract(member, td)

        for member in members:
            path = Path(td) / member
            with xr.open_dataset(path) as ds:
                var_name = _temperature_variable(ds)
                lat_name = _coord_name(ds, ("latitude", "lat"))
                lon_name = _coord_name(ds, ("longitude", "lon"))
                time_name = _coord_name(ds, ("valid_time", "time", "date"))
                units = str(ds[var_name].attrs.get("units", "K")).lower()

                for asset in assets:
                    selected = ds[var_name].sel(
                        {
                            lat_name: float(asset["latitude"]),
                            lon_name: float(asset["longitude"]),
                        },
                        method="nearest",
                    )
                    frame = selected.to_dataframe(name="temperature_raw").reset_index()
                    if time_name not in frame.columns:
                        raise ValueError(f"Time coordinate {time_name} not found in extracted data")
                    if units in {"k", "kelvin"}:
                        frame["temp_c"] = frame["temperature_raw"].astype(float) - 273.15
                    elif units in {"c", "degc", "celsius", "degree_celsius", "degrees_celsius"}:
                        frame["temp_c"] = frame["temperature_raw"].astype(float)
                    else:
                        raise ValueError(f"Unsupported temperature unit: {units}")

                    frame["date"] = pd.to_datetime(frame[time_name]).dt.date.astype(str)
                    frame["asset_location_id"] = asset["asset_location_id"]
                    frame["tenant_key"] = asset["tenant_key"]
                    frame["external_system"] = asset["external_system"]
                    frame["external_id"] = asset["external_id"]
                    frame["statistic"] = statistic
                    frame["source_artifact_id"] = source_artifact_id
                    frame["grid_latitude"] = float(selected[lat_name].values)
                    frame["grid_longitude"] = float(selected[lon_name].values)
                    rows.append(frame[[
                        "asset_location_id", "tenant_key", "external_system", "external_id",
                        "date", "statistic", "temp_c", "grid_latitude", "grid_longitude",
                        "source_artifact_id",
                    ]])

    if not rows:
        raise ValueError("No asset temperature rows extracted")
    out = pd.concat(rows, ignore_index=True)
    return out.drop_duplicates(
        subset=["asset_location_id", "date", "statistic"]
    ).sort_values(["asset_location_id", "date"]).reset_index(drop=True)


def annual_heat_indicators_from_daily(
    daily_max: pd.DataFrame,
    daily_min: pd.DataFrame,
    year: int,
) -> pd.DataFrame:
    required = {"asset_location_id", "tenant_key", "external_id", "date", "temp_c", "source_artifact_id"}
    if not required.issubset(daily_max.columns) or not required.issubset(daily_min.columns):
        raise ValueError("Daily frames missing required columns")

    rows = []
    for asset_id, x in daily_max.groupby("asset_location_id"):
        y = daily_min[daily_min["asset_location_id"] == asset_id]
        if y.empty:
            raise ValueError(f"Missing daily-min data for asset {asset_id}")
        x = x[pd.to_datetime(x["date"]).dt.year == int(year)]
        y = y[pd.to_datetime(y["date"]).dt.year == int(year)]
        if x.empty or y.empty:
            raise ValueError(f"No target-year data for asset {asset_id}")

        base = x.iloc[0]
        max_source = str(x["source_artifact_id"].iloc[0])
        min_source = str(y["source_artifact_id"].iloc[0])
        metrics = [
            ("days_tmax_gt_35c", float((x["temp_c"] > 35.0).sum()), max_source),
            ("days_tmax_gt_38c", float((x["temp_c"] > 38.0).sum()), max_source),
            ("warm_nights_gt_28c", float((y["temp_c"] > 28.0).sum()), min_source),
        ]
        for indicator_id, value, source_artifact_id in metrics:
            rows.append({
                "tenant_key": base["tenant_key"],
                "asset_location_id": asset_id,
                "external_id": base["external_id"],
                "indicator_id": indicator_id,
                "value": value,
                "unit": "days/year",
                "value_class": "CALCULATED",
                "measurement_basis": "CALCULATED_FROM_REANALYSIS",
                "source_artifact_id": source_artifact_id,
                "method_version": "ERA5_HEAT_0.1",
                "period_start": f"{year}-01-01T00:00:00+06:00",
                "period_end": f"{year}-12-31T23:59:59+06:00",
                "quality_flag": "OK",
            })
    return pd.DataFrame(rows)


def write_normalized_parquet(
    root: str | Path,
    frame: pd.DataFrame,
    *,
    year: int,
    statistic: str,
    run_id: str,
) -> Path:
    directory = parquet_partition_dir(
        root,
        layer="normalized",
        dataset="era5_land_daily_temperature",
        partitions={"year": year, "statistic": statistic},
    )
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"part-{run_id}.parquet"
    frame.to_parquet(path, index=False)
    register_parquet_dataset(
        root,
        dataset_name="era5_land_daily_temperature",
        layer="normalized",
        parquet_path=path,
        partition_spec={"year": year, "statistic": statistic},
        row_count=len(frame),
        run_id=run_id,
    )
    return path


def insert_heat_indicators(root: str | Path, frame: pd.DataFrame, run_id: str) -> int:
    count = 0
    with connect_catalog(root) as conn:
        for row in frame.to_dict(orient="records"):
            conn.execute(
                """
                INSERT INTO asset_indicator(
                    tenant_key,asset_location_id,indicator_id,value_numeric,value_text,
                    unit,value_class,measurement_basis,source_artifact_id,method_version,
                    period_start,period_end,quality_flag,null_reason,run_id,calculated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    row["tenant_key"], row["asset_location_id"], row["indicator_id"],
                    float(row["value"]), None, row["unit"], row["value_class"],
                    row["measurement_basis"], row["source_artifact_id"],
                    row["method_version"], row["period_start"], row["period_end"],
                    row["quality_flag"], None, run_id, utc_now(),
                ),
            )
            count += 1
        conn.commit()
    return count
