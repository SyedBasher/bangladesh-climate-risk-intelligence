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
    assert "**/.private-data-root" in text
    assert "**/audit_chain_secret.bin" in text
    assert "**/audit_head_anchor.json" in text
    assert "**/audit_head_anchor.pending.json" in text
    assert "**/audit_append.lock" in text
    assert "*.clrbackup" in text


def test_boundary_guard_catches_forced_private_files():
    bad = [
        "private_data/catalog/climate_risk.sqlite",
        "raw/era5/file.nc",
        "example.parquet",
        "pilot/.private-data-root",
        "pilot/workspace.json",
        "pilot/auth/audit_chain_secret.bin",
        "pilot/auth/audit_head_anchor.json",
        "pilot/auth/audit_head_anchor.pending.json",
        "pilot/auth/audit_append.lock",
        "pilot/auth/workspace_auth.json",
        "pilot/backups/recovery/private_pilot_20260924.clrbackup",
        "pilot/manifests/source_vintages/SRC/2026-09-24/abc.json",
        "pilot/manifests/plans/jrc_flood/asset_tile_plan.json",
        "pilot/normalized/assets/assets.parquet",
        "pilot/indicators/asset/evidence.json",
        "pilot/outputs/reports/TENANT_A/asset/A/decision-workspace-1.html",
        "pilot/outputs/qa/private-pilot-rehearsal-1.json",
        "pilot/backups/catalog/climate_risk.sqlite-wal",
        "pilot/tmp/clr-restore-rehearsal-x/auth/audit_chain_secret.bin",
    ]
    assert boundary_violations(bad) == sorted(bad)


def test_boundary_guard_does_not_flag_public_methodology_names():
    good = [
        "docs/normalized_methodology.md",
        "src/clr/indicators_helper.py",
        "examples/synthetic/decision_workspace_demo.html",
    ]
    assert boundary_violations(good) == []


def test_dockerignore_excludes_private_workspace_and_recovery_artifacts():
    dockerignore = (
        Path(__file__).resolve().parents[1] / ".dockerignore"
    ).read_text(encoding="utf-8")
    required = [
        "private_data",
        "**/.private-data-root",
        "**/audit_chain_secret.bin",
        "**/audit_head_anchor.json",
        "**/*.sqlite",
        "**/*.parquet",
        "**/*.clrbackup",
        ".env",
        "**/*.key",
    ]
    for item in required:
        assert item in dockerignore
