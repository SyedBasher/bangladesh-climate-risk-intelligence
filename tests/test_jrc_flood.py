import numpy as np
import rasterio
from rasterio.transform import from_origin
from clr.jrc_flood import extract_depth

def _write(path, value):
    data = np.full((10,10), value, dtype="float32")
    transform = from_origin(89.0, 26.0, 0.1, 0.1)
    with rasterio.open(path, "w", driver="GTiff", height=10, width=10, count=1, dtype="float32", crs="EPSG:4326", transform=transform, nodata=-9999) as ds:
        ds.write(data, 1)

def test_depth_and_masks(tmp_path):
    depth=tmp_path/"depth.tif"; pv=tmp_path/"pv.tif"; sp=tmp_path/"sp.tif"
    _write(depth, 1.25); _write(pv, 0); _write(sp, 1)
    r = extract_depth(depth, 25.5, 89.5, 100, pv, sp)
    assert abs(r.value-1.25) < 1e-6
    assert "SPURIOUS_DEPTH_MASK" in r.quality_flag
