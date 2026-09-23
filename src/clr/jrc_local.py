from __future__ import annotations

import json
import shutil
from pathlib import Path
from urllib.request import Request, urlopen

import pandas as pd

from .jrc_flood import (
    BASE,
    JRC_VERSION,
    load_tile_extents,
    permanent_water_filename,
    permanent_water_url,
    raw_depth_filename,
    raw_depth_url,
    resolve_tile,
    sample_raster_value,
    spurious_depth_filename,
    spurious_depth_url,
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

PROVIDER = "Copernicus Emergency Management Service / JRC"
PROVIDER_KEY = "JRC_CEMS"
DATASET_KEY = "GLOBAL_RIVER_FLOOD_HAZARD"
TILE_EXTENTS_URL = f"{BASE}/tile_extents.geojson"
DEFAULT_RETURN_PERIODS = (10, 50, 100)


def _download(url: str, target: Path, timeout: int = 120) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix(target.suffix + ".part")
    if part.exists():
        part.unlink()
    req = Request(
        url,
        headers={"User-Agent": "Mangrove-Climate-Risk/0.1 (+public-methodology-repository)"},
    )
    try:
        with urlopen(req, timeout=timeout) as response, open(part, "wb") as f:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
        if part.stat().st_size == 0:
            raise RuntimeError(f"Downloaded empty artifact: {url}")
        part.replace(target)
    except Exception:
        if part.exists():
            part.unlink()
        raise


def retrieve_public_artifact(
    root: str | Path,
    *,
    source_id: str,
    url: str,
    filename: str,
    note: str,
    media_type: str,
) -> dict:
    root = Path(root).resolve()

    # Reuse a previously registered, hash-verified artifact for the same
    # source/version before making another network request.
    with connect_catalog(root) as conn:
        rows = conn.execute(
            """
            SELECT * FROM source_artifact
            WHERE source_id=? AND provider_version=? AND retrieval_status='COMPLETE'
            ORDER BY retrieved_at DESC
            """,
            (source_id, JRC_VERSION),
        ).fetchall()
    for row in rows:
        cached = root / row["local_path"]
        if cached.exists() and sha256_file(cached) == row["sha256"]:
            return dict(row)

    tmp = root / "tmp" / filename
    if tmp.exists():
        tmp.unlink()
    _download(url, tmp)

    digest = sha256_file(tmp)
    destination = source_snapshot_path(
        root,
        PROVIDER_KEY,
        DATASET_KEY,
        JRC_VERSION,
        digest,
        filename,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if sha256_file(destination) != digest:
            raise RuntimeError("Content-addressed JRC destination has unexpected bytes")
        tmp.unlink()
    else:
        shutil.move(str(tmp), str(destination))

    return register_source_file(
        root,
        source_id=source_id,
        provider=PROVIDER,
        provider_version=JRC_VERSION,
        artifact_path=destination,
        media_type=media_type,
        retrieval_status="COMPLETE",
        note=note,
        request_parameters={"url": url},
    )


def ensure_tile_extents(root: str | Path) -> tuple[dict, Path]:
    root = Path(root).resolve()

    with connect_catalog(root) as conn:
        rows = conn.execute(
            """
            SELECT * FROM source_artifact
            WHERE source_id='JRC_TILE_EXTENTS'
              AND provider_version=?
              AND retrieval_status='COMPLETE'
            ORDER BY retrieved_at DESC
            """,
            (JRC_VERSION,),
        ).fetchall()

    for row in rows:
        path = root / row["local_path"]
        if path.exists() and sha256_file(path) == row["sha256"]:
            return dict(row), path

    record = retrieve_public_artifact(
        root,
        source_id="JRC_TILE_EXTENTS",
        url=TILE_EXTENTS_URL,
        filename="tile_extents.geojson",
        note="JRC tile-system spatial reference for Global river flood hazard maps.",
        media_type="application/geo+json",
    )
    return record, root / record["local_path"]


def asset_tile_plan(assets: list[dict], tile_extents_path: str | Path) -> pd.DataFrame:
    extents = load_tile_extents(tile_extents_path)
    rows = []
    for asset in assets:
        tile = resolve_tile(extents, float(asset["latitude"]), float(asset["longitude"]))
        rows.append({
            "asset_location_id": asset["asset_location_id"],
            "tenant_key": asset["tenant_key"],
            "external_system": asset["external_system"],
            "external_id": asset["external_id"],
            "latitude": float(asset["latitude"]),
            "longitude": float(asset["longitude"]),
            "tile_prefix": tile,
        })
    return pd.DataFrame(rows).sort_values(
        ["tile_prefix", "tenant_key", "external_system", "external_id"]
    ).reset_index(drop=True)


def artifact_plan(tile_prefixes, return_periods=DEFAULT_RETURN_PERIODS) -> list[dict]:
    rps = tuple(int(x) for x in return_periods)
    if not rps:
        raise ValueError("At least one return period is required")

    out = []
    for tile in sorted(set(tile_prefixes)):
        permanent = permanent_water_filename(tile)
        spurious = spurious_depth_filename(tile)
        out.append({
            "tile_prefix": tile,
            "role": "PERMANENT_WATER_MASK",
            "source_id": f"JRC_PERMANENT_WATER_{tile}",
            "filename": permanent,
            "url": permanent_water_url(permanent),
        })
        out.append({
            "tile_prefix": tile,
            "role": "SPURIOUS_DEPTH_MASK",
            "source_id": f"JRC_SPURIOUS_DEPTH_{tile}",
            "filename": spurious,
            "url": spurious_depth_url(spurious),
        })
        for rp in rps:
            name = raw_depth_filename(tile, rp)
            out.append({
                "tile_prefix": tile,
                "role": "DEPTH",
                "return_period": rp,
                "source_id": f"JRC_RP{rp}_{tile}",
                "filename": name,
                "url": raw_depth_url(rp, name),
            })
    return out


def retrieve_plan(root: str | Path, plan: list[dict]) -> dict[tuple, dict]:
    records = {}
    for item in plan:
        role = item["role"]
        record = retrieve_public_artifact(
            root,
            source_id=item["source_id"],
            url=item["url"],
            filename=item["filename"],
            note=(
                "JRC Global river flood hazard v2.1.2 "
                f"{role.lower().replace('_', ' ')} for tile {item['tile_prefix']}."
            ),
            media_type="image/tiff",
        )
        key = (
            item["tile_prefix"],
            role,
            item.get("return_period"),
        )
        records[key] = record
    return records


def extract_flood_rows(
    root: str | Path,
    asset_tiles: pd.DataFrame,
    records: dict[tuple, dict],
    *,
    return_periods=DEFAULT_RETURN_PERIODS,
) -> pd.DataFrame:
    root = Path(root).resolve()
    rows = []
    for asset in asset_tiles.to_dict(orient="records"):
        tile = asset["tile_prefix"]
        permanent_rec = records[(tile, "PERMANENT_WATER_MASK", None)]
        spurious_rec = records[(tile, "SPURIOUS_DEPTH_MASK", None)]
        permanent_path = root / permanent_rec["local_path"]
        spurious_path = root / spurious_rec["local_path"]

        permanent = sample_raster_value(
            permanent_path, asset["latitude"], asset["longitude"]
        )
        spurious = sample_raster_value(
            spurious_path, asset["latitude"], asset["longitude"]
        )

        for rp in return_periods:
            depth_rec = records[(tile, "DEPTH", int(rp))]
            depth_path = root / depth_rec["local_path"]
            raw_depth = sample_raster_value(
                depth_path, asset["latitude"], asset["longitude"]
            )

            published = raw_depth
            quality = "OK"
            null_reason = None

            if raw_depth is None:
                published = None
                quality = "NO_VALUE"
                null_reason = "SOURCE_NODATA"
            elif permanent not in (None, 0.0):
                # A site coordinate falling on mapped permanent water is not treated
                # as ordinary land-inundation depth. Preserve raw value in Parquet,
                # but block the production indicator pending review.
                published = None
                quality = "MASKED_PERMANENT_WATER"
                null_reason = "PERMANENT_WATER_MASK"
            elif spurious not in (None, 0.0):
                published = None
                quality = "MASKED_SPURIOUS_DEPTH"
                null_reason = "SPURIOUS_DEPTH_MASK"

            rows.append({
                **asset,
                "return_period": int(rp),
                "indicator_id": f"flood_rp{int(rp)}_depth_m",
                "raw_depth_m": raw_depth,
                "published_depth_m": published,
                "permanent_water_mask": permanent,
                "spurious_depth_mask": spurious,
                "quality_flag": quality,
                "null_reason": null_reason,
                "depth_source_artifact_id": depth_rec["source_artifact_id"],
                "permanent_water_source_artifact_id": permanent_rec["source_artifact_id"],
                "spurious_depth_source_artifact_id": spurious_rec["source_artifact_id"],
            })

    return pd.DataFrame(rows).sort_values(
        ["tenant_key", "external_system", "external_id", "return_period"]
    ).reset_index(drop=True)


def write_normalized_flood_parquet(
    root: str | Path,
    frame: pd.DataFrame,
    *,
    run_id: str,
) -> Path:
    directory = parquet_partition_dir(
        root,
        layer="normalized",
        dataset="jrc_flood_asset_extraction",
        partitions={"version": JRC_VERSION},
    )
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"part-{run_id}.parquet"
    frame.to_parquet(path, index=False)
    register_parquet_dataset(
        root,
        dataset_name="jrc_flood_asset_extraction",
        layer="normalized",
        parquet_path=path,
        partition_spec={"version": JRC_VERSION},
        row_count=len(frame),
        run_id=run_id,
    )
    return path


def insert_flood_indicators(
    root: str | Path,
    frame: pd.DataFrame,
    *,
    run_id: str,
    tile_extents_source_artifact_id: str,
) -> int:
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
                    None if pd.isna(row["published_depth_m"]) else float(row["published_depth_m"]),
                    None,
                    "m",
                    "SOURCE",
                    "HYDROLOGICAL_HYDRODYNAMIC_MODEL",
                    row["depth_source_artifact_id"],
                    f"JRC_FLOOD_{JRC_VERSION}",
                    None,
                    None,
                    row["quality_flag"],
                    row["null_reason"],
                    run_id,
                    utc_now(),
                ),
            )
            indicator_pk = cur.lastrowid
            lineage = [
                (indicator_pk, row["depth_source_artifact_id"], "DEPTH"),
                (
                    indicator_pk,
                    row["permanent_water_source_artifact_id"],
                    "PERMANENT_WATER_MASK",
                ),
                (
                    indicator_pk,
                    row["spurious_depth_source_artifact_id"],
                    "SPURIOUS_DEPTH_MASK",
                ),
                (indicator_pk, tile_extents_source_artifact_id, "TILE_EXTENTS"),
            ]
            conn.executemany(
                """
                INSERT INTO asset_indicator_source(
                    asset_indicator_id, source_artifact_id, source_role
                ) VALUES(?,?,?)
                """,
                lineage,
            )
            count += 1
        conn.commit()
    return count
