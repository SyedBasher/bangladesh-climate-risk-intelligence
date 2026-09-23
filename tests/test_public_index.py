from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_public_index_is_synthetic_and_non_scored():
    text = (ROOT / "index.html").read_text(encoding="utf-8")
    lower = text.lower()
    assert "synthetic public demonstration" in lower
    assert "no overall climate-risk score" in lower
    assert "real factory" in lower and "remain outside github" in lower


def test_public_index_shows_all_current_physical_layers():
    text = (ROOT / "index.html").read_text(encoding="utf-8")
    for required in [
        "ERA5-Land",
        "JRC/CEMS",
        "CHIRPS v3",
        "Copernicus DEM GLO-30",
    ]:
        assert required in text


def test_public_index_marks_surface_land_current_and_compound_next():
    text = (ROOT / "index.html").read_text(encoding="utf-8")
    assert "Exposure context pipeline" in text
    assert "Surface water &amp; land pipeline" in text
    assert "JRC Global Surface Water v1.5" in text
    assert "ESA WorldCover 2021 v200" in text
    assert "Compound Hazard &amp; Cross-Asset Intelligence" in text
    assert "Next build" in text
