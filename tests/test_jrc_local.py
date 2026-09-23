from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import rasterio
from rasterio.transform import from_origin

from clr.jrc_flood import (
    permanent_water_filename,
    raw_depth_filename,
    resolve_tile,
    spurious_depth_filename,
    tile_prefix_from_properties,
)
from clr.jrc_local import artifact_plan, extract_flood_rows


def _write_raster(path, value):
    data = np.full((10, 10), value, dtype="float32")
    transform = from_origin(80.0, 30.0, 1.0, 1.0)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=10,
        width=10,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=transform,
        nodata=-9999,
    ) as ds:
        ds.write(data, 1)


def _tile_extents():
    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {
                "unexpected_key": "ID999_N30_E80_RP100_depth.tif"
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[80,20],[90,20],[90,30],[80,30],[80,20]]],
            },
        }],
    }


def test_tile_prefix_is_discovered_independent_of_property_name():
    assert (
        tile_prefix_from_properties(
            {"anything": "ID999_N30_E80_RP100_depth_reclass.tif"}
        )
        == "ID999_N30_E80"
    )


def test_asset_resolves_to_exactly_one_tile():
    assert resolve_tile(_tile_extents(), 24.0, 90.0 - 0.1) == "ID999_N30_E80"


def test_official_filename_conventions():
    tile = "ID999_N30_E80"
    assert raw_depth_filename(tile, 100) == "ID999_N30_E80_RP100_depth.tif"
    assert permanent_water_filename(tile) == "ID999_N30_E80_permanent_water.tif"
    assert spurious_depth_filename(tile) == "ID999_N30_E80_spurious_depth_areas.tif"


def test_artifact_plan_requires_depth_and_both_masks():
    plan = artifact_plan(["ID999_N30_E80"], [10, 50, 100])
    roles = [x["role"] for x in plan]
    assert roles.count("PERMANENT_WATER_MASK") == 1
    assert roles.count("SPURIOUS_DEPTH_MASK") == 1
    assert roles.count("DEPTH") == 3
    urls = " ".join(x["url"] for x in plan)
    assert "/Permanent_WaterBodies/" in urls
    assert "/Spurious_Depths/" in urls
    assert "/RP100/" in urls


def test_spurious_mask_blocks_published_depth_but_preserves_raw(tmp_path):
    root = tmp_path
    depth = root / "depth.tif"
    perm = root / "perm.tif"
    spur = root / "spur.tif"
    _write_raster(depth, 12.0)
    _write_raster(perm, 0.0)
    _write_raster(spur, 1.0)

    records = {
        ("ID999_N30_E80", "PERMANENT_WATER_MASK", None): {
            "local_path": "perm.tif",
            "source_artifact_id": "PERM",
        },
        ("ID999_N30_E80", "SPURIOUS_DEPTH_MASK", None): {
            "local_path": "spur.tif",
            "source_artifact_id": "SPUR",
        },
        ("ID999_N30_E80", "DEPTH", 100): {
            "local_path": "depth.tif",
            "source_artifact_id": "DEPTH",
        },
    }
    assets = pd.DataFrame([{
        "asset_location_id": "A1",
        "tenant_key": "INTERNAL",
        "external_system": "SYNTH",
        "external_id": "X",
        "latitude": 25.0,
        "longitude": 85.0,
        "tile_prefix": "ID999_N30_E80",
    }])
    out = extract_flood_rows(root, assets, records, return_periods=[100])
    row = out.iloc[0]
    assert row["raw_depth_m"] == 12.0
    assert pd.isna(row["published_depth_m"])
    assert row["null_reason"] == "SPURIOUS_DEPTH_MASK"
    assert row["quality_flag"] == "MASKED_SPURIOUS_DEPTH"


def test_permanent_water_blocks_published_depth(tmp_path):
    root = tmp_path
    depth = root / "depth.tif"
    perm = root / "perm.tif"
    spur = root / "spur.tif"
    _write_raster(depth, 1.2)
    _write_raster(perm, 1.0)
    _write_raster(spur, 0.0)

    records = {
        ("ID999_N30_E80", "PERMANENT_WATER_MASK", None): {
            "local_path": "perm.tif",
            "source_artifact_id": "PERM",
        },
        ("ID999_N30_E80", "SPURIOUS_DEPTH_MASK", None): {
            "local_path": "spur.tif",
            "source_artifact_id": "SPUR",
        },
        ("ID999_N30_E80", "DEPTH", 50): {
            "local_path": "depth.tif",
            "source_artifact_id": "DEPTH",
        },
    }
    assets = pd.DataFrame([{
        "asset_location_id": "A1",
        "tenant_key": "INTERNAL",
        "external_system": "SYNTH",
        "external_id": "X",
        "latitude": 25.0,
        "longitude": 85.0,
        "tile_prefix": "ID999_N30_E80",
    }])
    out = extract_flood_rows(root, assets, records, return_periods=[50])
    row = out.iloc[0]
    assert row["raw_depth_m"] == pytest.approx(1.2)
    assert pd.isna(row["published_depth_m"])
    assert row["null_reason"] == "PERMANENT_WATER_MASK"
