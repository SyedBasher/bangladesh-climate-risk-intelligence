import zipfile
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from clr.copdem_local import (
    PRODUCT_TYPE,
    copdem_grid_id,
    extract_dem_raster,
    select_latest_product,
)
from clr.local_store import initialize_workspace, register_source_file


def schema_path():
    return Path(__file__).resolve().parents[1] / "migrations" / "000_local_private_data_plane.sql"


def _product(product_id, dataset, grid="N23_E090"):
    return {
        "Id": product_id,
        "Name": f"Copernicus_DSM_10_{grid}_TEST",
        "Attributes": [
            {"Name": "gridId", "Value": grid},
            {"Name": "dataset", "Value": dataset},
            {"Name": "delivery", "Value": dataset.split("/")[-1]},
            {"Name": "productType", "Value": PRODUCT_TYPE},
        ],
    }


def test_grid_id_uses_southwest_one_degree_cell():
    assert copdem_grid_id(23.9, 90.4) == "N23_E090"
    assert copdem_grid_id(24.0, 90.0) == "N24_E090"
    assert copdem_grid_id(-0.2, -1.2) == "S01_W002"


def test_latest_delivery_is_selected_from_dataset_suffix():
    products = [
        _product("old", "COP-DEM_GLO-30-DGED/2023_1"),
        _product("new", "COP-DEM_GLO-30-DGED/2024_1"),
    ]
    selected = select_latest_product(products, "N23_E090")
    assert selected["id"] == "new"
    assert selected["dataset"] == "COP-DEM_GLO-30-DGED/2024_1"


def test_ambiguous_latest_delivery_fails_closed():
    products = [
        _product("a", "COP-DEM_GLO-30-DGED/2024_1"),
        _product("b", "COP-DEM_GLO-30-DGED/2024_1"),
    ]
    with pytest.raises(ValueError, match="Ambiguous latest"):
        select_latest_product(products, "N23_E090")


def _write_dem(path):
    data = np.full((5, 5), 7.0, dtype="float32")
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=5,
        width=5,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(90, 24, 0.01, 0.01),
    ) as ds:
        ds.write(data, 1)


def test_dem_member_is_extracted_and_registered(tmp_path):
    root = tmp_path / "private_data"
    initialize_workspace(root, schema_path())

    tif = root / "tmp" / "Copernicus_DSM_10_N23_00_E090_00_DEM.tif"
    _write_dem(tif)
    package = root / "raw" / "package.zip"
    package.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(package, "w") as z:
        z.write(tif, arcname=f"PRODUCT/{tif.name}")
    tif.unlink()

    package_record = register_source_file(
        root,
        source_id="COPDEM_PACKAGE_SYNTH",
        provider="Copernicus",
        provider_version="COP-DEM_GLO-30-DGED/2024_1",
        artifact_path=package,
        retrieved_at="2026-09-23T00:00:00+00:00",
    )
    product = {
        "id": "12345678-1234-1234-1234-123456789abc",
        "name": "Synthetic",
        "grid_id": "N23_E090",
        "dataset": "COP-DEM_GLO-30-DGED/2024_1",
        "delivery": "2024_1",
        "product_type": PRODUCT_TYPE,
        "s3_path": None,
        "content_date": None,
    }

    record = extract_dem_raster(
        root,
        package_record,
        grid_id="N23_E090",
        product=product,
    )
    assert (root / record["local_path"]).exists()
    assert record["provider_version"] == "COP-DEM_GLO-30-DGED/2024_1"
    assert record["local_path"].endswith("_DEM.tif")
