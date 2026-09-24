import fnmatch
import subprocess
from pathlib import Path

from clr.local_store import WORKSPACE_DIRS
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


def _docker_patterns():
    return [
        line.strip()
        for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def test_boundary_guard_tracks_every_canonical_workspace_directory():
    candidates = [
        f"pilot/{rel.strip('/')}/synthetic-private.txt"
        for rel in WORKSPACE_DIRS
    ]
    assert boundary_violations(candidates) == sorted(candidates)


def test_gitignore_behaviour_covers_custom_root_workspace_layout():
    for rel in WORKSPACE_DIRS:
        candidate = f"pilot/{rel.strip('/')}/synthetic-private.txt"
        result = subprocess.run(
            [
                "git",
                "check-ignore",
                "--no-index",
                "-q",
                "--",
                candidate,
            ],
            cwd=ROOT,
            check=False,
        )
        assert result.returncode == 0, candidate


def test_gitignore_has_no_blank_rule_trap_and_auth_is_explicitly_ignored():
    lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert all(line.strip() for line in lines)
    result = subprocess.run(
        [
            "git",
            "check-ignore",
            "--no-index",
            "-v",
            "--",
            "pilot/auth/synthetic.json",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "**/auth/" in result.stdout
    assert ":\t" not in result.stdout


def test_dockerignore_behaviour_covers_custom_root_workspace_layout():
    patterns = _docker_patterns()
    candidates = [
        "pilot/auth/private.json",
        "pilot/catalog/private.json",
        "pilot/raw/era5_land/private.json",
        "pilot/normalized/assets/private.json",
        "pilot/indicators/asset/private.json",
        "pilot/manifests/plans/private.json",
        "pilot/outputs/reports/private.html",
        "pilot/tmp/private.json",
        "pilot/backups/recovery/private.json",
    ]
    for candidate in candidates:
        assert any(
            fnmatch.fnmatchcase(candidate, pattern)
            for pattern in patterns
        ), candidate
