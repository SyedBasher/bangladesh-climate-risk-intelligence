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


def test_public_index_marks_decision_reports_current():
    text = (ROOT / "index.html").read_text(encoding="utf-8")
    assert "Surface water &amp; land pipeline" in text
    assert "Compound intelligence pipeline" in text
    assert "Decision reports pipeline" in text
    assert "ERA5-Land + CHIRPS" in text
    assert "OSM + JRC/CEMS" in text
    assert "Decision Reports &amp; Portfolio Workspace" in text
    assert "Current product layer" in text
    assert "examples/synthetic/decision_workspace_demo.html" in text
    assert "Private authenticated workspace: local-only shell" in text
    assert "hosted private pilot &amp; access-control hardening" in text
