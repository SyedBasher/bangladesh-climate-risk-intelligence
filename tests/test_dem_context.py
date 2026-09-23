import numpy as np
import rasterio
from rasterio.transform import from_origin

from clr.dem import dsm_context, dsm_context_indicators


def _write_context_raster(path):
    data = np.full((101, 101), 10.0, dtype="float32")
    data[50, 50] = 8.0
    transform = from_origin(90.0, 24.1, 0.001, 0.001)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=101,
        width=101,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=transform,
        nodata=-32767,
    ) as ds:
        ds.write(data, 1)


def test_dsm_relative_elevation_uses_local_median(tmp_path):
    path = tmp_path / "dem.tif"
    _write_context_raster(path)
    ctx = dsm_context(path, 24.0495, 90.0505, radius_m=500)
    assert abs(ctx["point_elevation_m"] - 8.0) < 1e-6
    assert abs(ctx["local_median_m"] - 10.0) < 1e-6
    assert abs(ctx["relative_elevation_m"] + 2.0) < 1e-6
    assert abs(ctx["local_relief_p90_p10_m"]) < 1e-6
    assert ctx["quality_flag"] == "OK"


def test_dsm_context_indicator_names_are_explicit(tmp_path):
    path = tmp_path / "dem.tif"
    _write_context_raster(path)
    out = {
        x.indicator_id: x
        for x in dsm_context_indicators(
            path,
            24.0495,
            90.0505,
            "COPDEM_SYNTHETIC",
            radius_m=500,
        )
    }
    assert set(out) == {
        "elevation_dsm_m",
        "dsm_relative_elevation_500m_m",
        "dsm_local_relief_p90_p10_500m_m",
    }
    assert out["elevation_dsm_m"].value_class == "SOURCE"
    assert out["dsm_relative_elevation_500m_m"].value_class == "CALCULATED"
    assert "SURFACE_MODEL" in out["elevation_dsm_m"].measurement_basis
