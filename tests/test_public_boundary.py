from pathlib import Path

from clr.public_boundary import boundary_violations, tracked_files


ROOT = Path(__file__).resolve().parents[1]


def test_git_tracks_no_private_data_paths_or_binary_data():
    tracked = tracked_files(ROOT)
    assert boundary_violations(tracked) == []


def test_gitignore_explicitly_blocks_private_workspace():
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "private_data/" in text
    assert "*.parquet" in text
    assert "*.sqlite" in text


def test_boundary_guard_catches_forced_private_files():
    bad = [
        "private_data/catalog/climate_risk.sqlite",
        "raw/era5/file.nc",
        "example.parquet",
    ]
    assert boundary_violations(bad) == sorted(bad)
