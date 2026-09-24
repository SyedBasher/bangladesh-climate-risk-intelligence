import json
from pathlib import Path

import pytest

from clr.local_assets import import_asset_rows
from clr.local_store import (
    connect_catalog,
    finish_processing_run,
    initialize_workspace,
    register_source_file,
    start_processing_run,
    utc_now,
)
from clr.private_workspace_app import (
    _safe_output_file,
    render_dashboard,
    serve_private_workspace,
    tenant_exists,
    workspace_catalog,
)
from clr.private_workspace_auth import (
    create_session_token,
    set_workspace_password,
    validate_csrf,
    verify_session_token,
    verify_workspace_password,
)


ROOT = Path(__file__).resolve().parents[1]


def schema_path():
    return ROOT / "migrations" / "000_local_private_data_plane.sql"


def _workspace(tmp_path):
    root = tmp_path / "private_data"
    initialize_workspace(root, schema_path())
    import_asset_rows(
        root,
        [
            {
                "external_system": "SYNTH",
                "external_id": "A",
                "asset_type": "FACTORY",
                "latitude": 24.0,
                "longitude": 90.4,
                "coordinate_source": "SYNTHETIC",
                "site_identity_grade": "EXACT_SITE",
                "coordinate_status": "RESOLVED",
            }
        ],
        tenant_key="TENANT_A",
    )
    import_asset_rows(
        root,
        [
            {
                "external_system": "SYNTH",
                "external_id": "B",
                "asset_type": "FACTORY",
                "latitude": 23.9,
                "longitude": 90.3,
                "coordinate_source": "SYNTHETIC",
                "site_identity_grade": "EXACT_SITE",
                "coordinate_status": "RESOLVED",
            }
        ],
        tenant_key="TENANT_B",
    )
    source_file = root / "raw" / "era5_land" / "synthetic.bin"
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_bytes(b"synthetic source")
    source = register_source_file(
        root,
        source_id="SYNTH_SOURCE",
        provider="SYNTHETIC",
        provider_version="v1",
        artifact_path=source_file,
        retrieved_at="2026-09-24T00:00:00+00:00",
    )
    with connect_catalog(root) as conn:
        a = conn.execute(
            "SELECT * FROM asset_location WHERE tenant_key='TENANT_A'"
        ).fetchone()
        b = conn.execute(
            "SELECT * FROM asset_location WHERE tenant_key='TENANT_B'"
        ).fetchone()
    return root, source, dict(a), dict(b)


def _indicator_run(root, source, asset, tenant):
    run_id = start_processing_run(
        root,
        pipeline_name="synthetic_indicator",
        pipeline_version="0.1",
        git_commit="syntheticsha",
        parameters={"tenant": tenant, "year": 2025},
    )
    with connect_catalog(root) as conn:
        cur = conn.execute(
            """
            INSERT INTO asset_indicator(
                tenant_key,asset_location_id,indicator_id,value_numeric,value_text,
                unit,value_class,measurement_basis,source_artifact_id,method_version,
                period_start,period_end,quality_flag,null_reason,run_id,calculated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                tenant,
                asset["asset_location_id"],
                "flood_rp100_depth_m",
                0.5,
                None,
                "m",
                "SOURCE",
                "HYDROLOGICAL_HYDRODYNAMIC_MODEL",
                source["source_artifact_id"],
                "SYNTH",
                None,
                None,
                "OK",
                None,
                run_id,
                utc_now(),
            ),
        )
        conn.execute(
            """
            INSERT INTO asset_indicator_source(
                asset_indicator_id,source_artifact_id,source_role
            ) VALUES(?,?,?)
            """,
            (cur.lastrowid, source["source_artifact_id"], "PRIMARY"),
        )
        conn.commit()
    finish_processing_run(root, run_id, status="SUCCESS")
    return run_id


def test_workspace_password_is_hashed_and_not_stored_in_plaintext(tmp_path):
    root, _, _, _ = _workspace(tmp_path)
    password = "synthetic-long-password"
    result = set_workspace_password(root, password, iterations=100_000)
    credential = root / result["credential_path"]
    text = credential.read_text(encoding="utf-8")
    assert password not in text
    payload = json.loads(text)
    assert payload["kdf"] == "PBKDF2-HMAC-SHA256"
    assert payload["iterations"] == 100_000
    assert verify_workspace_password(root, password)
    assert not verify_workspace_password(root, "wrong-password-123")


def test_session_token_is_signed_tenant_bound_and_expires(tmp_path):
    root, _, _, _ = _workspace(tmp_path)
    set_workspace_password(root, "synthetic-long-password", iterations=100_000)
    token, issued = create_session_token(
        root,
        tenant_key="TENANT_A",
        ttl_seconds=600,
        now=1_000,
    )
    verified = verify_session_token(root, token, now=1_100)
    assert verified is not None
    assert verified["tenant"] == "TENANT_A"
    assert validate_csrf(verified, issued["csrf"])
    assert not validate_csrf(verified, "bad")
    assert verify_session_token(root, token + "tamper", now=1_100) is None
    assert verify_session_token(root, token, now=1_700) is None


def test_workspace_catalog_is_tenant_scoped_and_omits_coordinates(tmp_path):
    root, source, asset_a, asset_b = _workspace(tmp_path)
    run_a = _indicator_run(root, source, asset_a, "TENANT_A")
    _indicator_run(root, source, asset_b, "TENANT_B")
    with connect_catalog(root) as conn:
        conn.execute(
            """
            INSERT INTO portfolio_exposure(
                portfolio_exposure_id,tenant_key,portfolio_id,exposure_id,
                borrower_id,asset_location_id,exposure_type,amount,currency,
                valuation_date,metadata_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "PX_A",
                "TENANT_A",
                "P_A",
                "E_A",
                "BORROWER_SECRET",
                asset_a["asset_location_id"],
                "EAD",
                100.0,
                "BDT",
                "2026-09-24",
                "{}",
            ),
        )
        conn.commit()

    catalog = workspace_catalog(root, "TENANT_A")
    serialized = json.dumps(catalog)
    assert [x["external_id"] for x in catalog["assets"]] == ["A"]
    assert [x["portfolio_id"] for x in catalog["portfolios"]] == ["P_A"]
    assert [x["run_id"] for x in catalog["indicator_runs"]] == [run_a]
    assert "latitude" not in serialized.lower()
    assert "longitude" not in serialized.lower()
    assert "BORROWER_SECRET" not in serialized
    assert tenant_exists(root, "TENANT_A")
    assert tenant_exists(root, "TENANT_B")
    assert not tenant_exists(root, "UNKNOWN")


def test_dashboard_does_not_render_private_coordinates_or_borrowers(tmp_path):
    root, source, asset_a, _ = _workspace(tmp_path)
    _indicator_run(root, source, asset_a, "TENANT_A")
    catalog = workspace_catalog(root, "TENANT_A")
    html = render_dashboard(catalog, csrf="synthetic-csrf")
    lower = html.lower()
    assert "decision workspace" in lower
    assert "latitude" not in lower
    assert "longitude" not in lower
    assert "borrower" not in lower
    assert "synthetic-csrf" in html


def test_report_file_access_is_confined_to_authenticated_tenant(tmp_path):
    root, _, _, _ = _workspace(tmp_path)
    a_dir = root / "outputs" / "reports" / "TENANT_A" / "asset" / "A"
    b_dir = root / "outputs" / "reports" / "TENANT_B" / "asset" / "B"
    a_dir.mkdir(parents=True, exist_ok=True)
    b_dir.mkdir(parents=True, exist_ok=True)
    a_file = a_dir / "report.html"
    b_file = b_dir / "report.html"
    a_file.write_text("<html>A</html>", encoding="utf-8")
    b_file.write_text("<html>B</html>", encoding="utf-8")

    resolved = _safe_output_file(
        root,
        "TENANT_A",
        a_file.relative_to(root).as_posix(),
        suffixes=(".html",),
    )
    assert resolved == a_file.resolve()

    with pytest.raises(ValueError, match="outside the authenticated tenant"):
        _safe_output_file(
            root,
            "TENANT_A",
            b_file.relative_to(root).as_posix(),
            suffixes=(".html",),
        )

    with pytest.raises(ValueError):
        _safe_output_file(
            root,
            "TENANT_A",
            "../../outside.html",
            suffixes=(".html",),
        )


def test_server_refuses_non_loopback_binding(tmp_path):
    root, _, _, _ = _workspace(tmp_path)
    with pytest.raises(ValueError, match="localhost-only"):
        serve_private_workspace(root, host="0.0.0.0", port=8765)
