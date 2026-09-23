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


def test_public_index_marks_logistics_as_current_and_event_validation_next():
    text = (ROOT / "index.html").read_text(encoding="utf-8")
    assert "Logistics pipeline" in text
    assert "Observed Flood &amp; Event Validation" in text
    assert "Next build" in text
