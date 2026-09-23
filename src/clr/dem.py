from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import rasterio
from rasterio.windows import Window

from .common import IndicatorResult, require_coordinate

COPDEM_MEASUREMENT_BASIS = "STATIC_DIGITAL_SURFACE_MODEL"
COPDEM_CALCULATED_BASIS = "CALCULATED_FROM_STATIC_DIGITAL_SURFACE_MODEL"


def _sample(path: str | Path, lat: float, lon: float) -> float | None:
    require_coordinate(lat, lon)
    with rasterio.open(path) as ds:
        x, y = lon, lat
        if ds.crs and str(ds.crs).upper() not in ("EPSG:4326", "OGC:CRS84"):
            from rasterio.warp import transform
            xs, ys = transform("EPSG:4326", ds.crs, [lon], [lat])
            x, y = xs[0], ys[0]
        arr = list(ds.sample([(x, y)], masked=True))[0]
        try:
            if arr.mask[0]:
                return None
        except Exception:
            pass
        val = float(arr[0])
        return val if math.isfinite(val) else None


def sample_elevation(
    path: str | Path,
    lat: float,
    lon: float,
    source_vintage: str,
) -> IndicatorResult:
    value = _sample(path, lat, lon)
    if value is None:
        return IndicatorResult(
            "elevation_dsm_m",
            None,
            "m",
            "SOURCE",
            COPDEM_MEASUREMENT_BASIS,
            quality_flag="NO_VALUE",
            null_reason="SOURCE_NODATA",
            source_vintage=source_vintage,
        )
    return IndicatorResult(
        "elevation_dsm_m",
        value,
        "m",
        "SOURCE",
        COPDEM_MEASUREMENT_BASIS,
        source_vintage=source_vintage,
    )


def dsm_context(
    path: str | Path,
    lat: float,
    lon: float,
    *,
    radius_m: float = 500.0,
    min_valid_fraction: float = 0.80,
) -> dict:
    """Return DSM point and robust local-context statistics.

    This is surface elevation, not bare-earth terrain. For geographic grids,
    metre spacing is approximated locally from latitude.
    """
    require_coordinate(lat, lon)
    if radius_m <= 0:
        raise ValueError("radius_m must be positive")
    if not (0 < min_valid_fraction <= 1):
        raise ValueError("min_valid_fraction must be in (0,1]")

    with rasterio.open(path) as ds:
        x, y = lon, lat
        geographic = not ds.crs or str(ds.crs).upper() in ("EPSG:4326", "OGC:CRS84")
        if not geographic:
            from rasterio.warp import transform
            xs, ys = transform("EPSG:4326", ds.crs, [lon], [lat])
            x, y = xs[0], ys[0]

        point_arr = list(ds.sample([(x, y)], masked=True))[0]
        try:
            point_masked = bool(point_arr.mask[0])
        except Exception:
            point_masked = False
        if point_masked or not math.isfinite(float(point_arr[0])):
            return {
                "point_elevation_m": None,
                "local_median_m": None,
                "relative_elevation_m": None,
                "local_relief_p90_p10_m": None,
                "valid_fraction": 0.0,
                "quality_flag": "SOURCE_NODATA",
                "null_reason": "SOURCE_NODATA",
            }

        point = float(point_arr[0])
        row, col = ds.index(x, y)

        if geographic:
            metres_per_deg_lat = 111_320.0
            metres_per_deg_lon = max(1.0, 111_320.0 * math.cos(math.radians(lat)))
            px_y_m = abs(ds.transform.e) * metres_per_deg_lat
            px_x_m = abs(ds.transform.a) * metres_per_deg_lon
        else:
            px_x_m = abs(ds.transform.a)
            px_y_m = abs(ds.transform.e)

        if px_x_m <= 0 or px_y_m <= 0:
            raise ValueError("Invalid raster pixel spacing")

        row_radius = max(1, int(math.ceil(radius_m / px_y_m)))
        col_radius = max(1, int(math.ceil(radius_m / px_x_m)))

        window = Window(
            col - col_radius,
            row - row_radius,
            2 * col_radius + 1,
            2 * row_radius + 1,
        )
        arr = ds.read(1, window=window, boundless=True, masked=True)

        rr, cc = np.indices(arr.shape)
        center_r = row_radius
        center_c = col_radius
        distances = np.sqrt(
            ((rr - center_r) * px_y_m) ** 2
            + ((cc - center_c) * px_x_m) ** 2
        )
        circle = distances <= radius_m
        total = int(circle.sum())
        valid = circle & ~np.ma.getmaskarray(arr)
        values = np.asarray(arr.data[valid], dtype=float)
        values = values[np.isfinite(values)]
        valid_fraction = 0.0 if total == 0 else float(len(values) / total)

        if len(values) == 0 or valid_fraction < min_valid_fraction:
            return {
                "point_elevation_m": point,
                "local_median_m": None,
                "relative_elevation_m": None,
                "local_relief_p90_p10_m": None,
                "valid_fraction": valid_fraction,
                "quality_flag": "INSUFFICIENT_NEIGHBORHOOD_COVERAGE",
                "null_reason": "INSUFFICIENT_NEIGHBORHOOD_COVERAGE",
            }

        median = float(np.median(values))
        p10, p90 = np.quantile(values, [0.10, 0.90])
        return {
            "point_elevation_m": point,
            "local_median_m": median,
            "relative_elevation_m": point - median,
            "local_relief_p90_p10_m": float(p90 - p10),
            "valid_fraction": valid_fraction,
            "quality_flag": "OK",
            "null_reason": None,
        }


def dsm_context_indicators(
    path: str | Path,
    lat: float,
    lon: float,
    source_vintage: str,
    *,
    radius_m: float = 500.0,
) -> list[IndicatorResult]:
    ctx = dsm_context(path, lat, lon, radius_m=radius_m)
    point = ctx["point_elevation_m"]
    results = [
        IndicatorResult(
            "elevation_dsm_m",
            point,
            "m",
            "SOURCE",
            COPDEM_MEASUREMENT_BASIS,
            quality_flag="OK" if point is not None else ctx["quality_flag"],
            null_reason=None if point is not None else ctx["null_reason"],
            source_vintage=source_vintage,
        )
    ]

    radius_label = int(radius_m)
    for indicator_id, value in (
        (f"dsm_relative_elevation_{radius_label}m_m", ctx["relative_elevation_m"]),
        (f"dsm_local_relief_p90_p10_{radius_label}m_m", ctx["local_relief_p90_p10_m"]),
    ):
        results.append(
            IndicatorResult(
                indicator_id,
                value,
                "m",
                "CALCULATED",
                COPDEM_CALCULATED_BASIS,
                quality_flag="OK" if value is not None else ctx["quality_flag"],
                null_reason=None if value is not None else ctx["null_reason"],
                source_vintage=source_vintage,
            )
        )
    return results
