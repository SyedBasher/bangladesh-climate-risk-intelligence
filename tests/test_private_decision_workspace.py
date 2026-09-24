import json
from pathlib import Path

import pytest

from clr.compound_local import _insert_cross_metric
from clr.local_assets import import_asset_rows
from clr.local_store import (
    connect_catalog,
    finish_processing_run,
    initialize_workspace,
    register_source_file,
    start_processing_run,
    utc_now,
)
from clr.private_decision_workspace import (
    build_and_write_private_decision_workspace,
    build_private_decision_workspace,
)


ROOT = Path(__file__).resolve().parents[1]


def schema_path():
    return ROOT / "migrations" / "000_local_private_data_plane.sql"


def _workspace(tmp_path):
    root = tmp_path / "private_data"
    initialize_workspace(root, schema_path())
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
    result = import_asset_rows(
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
            },
            {
                "external_system": "SYNTH",
                "external_id": "B",
                "asset_type": "FACTORY",
                "latitude": 23.9,
                "longitude": 90.3,
                "coordinate_source": "SYNTHETIC",
                "site_identity_grade": "EXACT_SITE",
                "coordinate_status": "RESOLVED",
            },
        ],
        tenant_key="INTERNAL",
    )
    assert result["inserted"] == 2
    with connect_catalog(root) as conn:
        assets = {
            row["external_id"]: dict(row)
            for row in conn.execute(
                "SELECT * FROM asset_location WHERE tenant_key='INTERNAL'"
            ).fetchall()
        }
    return root, source, assets


def _successful_indicator_run(root, source, assets, *, pipeline="synthetic_indicators"):
    run_id = start_processing_run(
        root,
        pipeline_name=pipeline,
        pipeline_version="0.1",
        git_commit="syntheticsha",
        parameters={"year": 2025},
    )
    with connect_catalog(root) as conn:
        for asset_key, depth in [("A", 0.6), ("B", 0.0)]:
            cur = conn.execute(
                """
                INSERT INTO asset_indicator(
                    tenant_key,asset_location_id,indicator_id,value_numeric,value_text,
                    unit,value_class,measurement_basis,source_artifact_id,method_version,
                    period_start,period_end,quality_flag,null_reason,run_id,calculated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    "INTERNAL",
                    assets[asset_key]["asset_location_id"],
                    "flood_rp100_depth_m",
                    depth,
                    None,
                    "m",
                    "SOURCE",
                    "HYDROLOGICAL_HYDRODYNAMIC_MODEL",
                    source["source_artifact_id"],
                    "SYNTH_FLOOD_0.1",
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
        conn.execute(
            """
            INSERT INTO asset_indicator(
                tenant_key,asset_location_id,indicator_id,value_numeric,value_text,
                unit,value_class,measurement_basis,source_artifact_id,method_version,
                period_start,period_end,quality_flag,null_reason,run_id,calculated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "INTERNAL",
                assets["A"]["asset_location_id"],
                "days_tmax_gt_35c",
                24.0,
                None,
                "days",
                "CALCULATED",
                "CALCULATED_FROM_REANALYSIS",
                source["source_artifact_id"],
                "SYNTH_HEAT_0.1",
                "2025-01-01",
                "2025-12-31",
                "OK",
                None,
                run_id,
                utc_now(),
            ),
        )
        conn.commit()
    finish_processing_run(root, run_id, status="SUCCESS")
    return run_id


def test_asset_adapter_uses_explicit_run_and_writes_only_private_outputs(tmp_path):
    root, source, assets = _workspace(tmp_path)
    run_id = _successful_indicator_run(root, source, assets)

    result = build_and_write_private_decision_workspace(
        root,
        scope_type="ASSET",
        tenant_key="INTERNAL",
        indicator_run_ids=[run_id],
        asset_location_id=assets["A"]["asset_location_id"],
    )

    assert result["selection"]["indicator_run_ids"] == [run_id]
    assert result["scope"]["subject_id"] == "SYNTH:A"
    for rel in result["outputs"].values():
        assert rel.startswith("outputs/reports/")
        assert (root / rel).exists()

    report = json.loads((root / result["outputs"]["json"]).read_text(encoding="utf-8"))
    assert report["direct_physical_evidence"][0]["source_id"] == "SYNTH_SOURCE"
    assert report["data_readiness"]["site_identity_grade"] == "EXACT_SITE"
    assert "latitude" not in json.dumps(report).lower()
    assert "longitude" not in json.dumps(report).lower()
    assert "risk_score" not in json.dumps(report).lower()

    manifest = json.loads(
        (root / result["outputs"]["manifest"]).read_text(encoding="utf-8")
    )
    assert manifest["output_policy"] == "PRIVATE_WORKSPACE_ONLY"
    assert manifest["selection"]["indicator_run_ids"] == [run_id]
    assert len(manifest["json_sha256"]) == 64
    assert len(manifest["html_sha256"]) == 64


def test_adapter_rejects_running_or_partial_indicator_run(tmp_path):
    root, source, assets = _workspace(tmp_path)
    run_id = start_processing_run(
        root,
        pipeline_name="unfinished",
        pipeline_version="0.1",
    )
    with pytest.raises(ValueError, match="only SUCCESS runs"):
        build_private_decision_workspace(
            root,
            scope_type="ASSET",
            tenant_key="INTERNAL",
            indicator_run_ids=[run_id],
            asset_location_id=assets["A"]["asset_location_id"],
        )


def test_adapter_fails_on_overlapping_indicator_vintages(tmp_path):
    root, source, assets = _workspace(tmp_path)
    first = _successful_indicator_run(root, source, assets, pipeline="first")
    second = _successful_indicator_run(root, source, assets, pipeline="second")
    with pytest.raises(ValueError, match="overlapping indicator vintages"):
        build_private_decision_workspace(
            root,
            scope_type="ASSET",
            tenant_key="INTERNAL",
            indicator_run_ids=[first, second],
            asset_location_id=assets["A"]["asset_location_id"],
        )


def test_compound_run_requires_explicit_matching_tenant_and_preserves_denominator(tmp_path):
    root, source, assets = _workspace(tmp_path)
    indicator_run = _successful_indicator_run(root, source, assets)
    compound_run = start_processing_run(
        root,
        pipeline_name="compound_cross_asset_intelligence",
        pipeline_version="0.1.0",
        parameters={"tenant": "INTERNAL", "year": 2025, "return_period": 100},
    )
    _insert_cross_metric(
        root,
        tenant_key="INTERNAL",
        analysis_type="HEAT_DROUGHT",
        metric_id="asset_share_with_heat_spi3_cooccurrence",
        value=0.5,
        unit="share",
        period_start="2025-01-01",
        period_end="2025-12-31",
        method_version="SYNTH",
        quality_flag="OK",
        input_manifest={"inputs": [{"dataset_name": "synthetic"}]},
        run_id=compound_run,
        source_roles={"HEAT_SOURCE": {source["source_artifact_id"]}},
        denominator=2,
    )
    finish_processing_run(root, compound_run, status="SUCCESS")

    report, selection = build_private_decision_workspace(
        root,
        scope_type="ASSET",
        tenant_key="INTERNAL",
        indicator_run_ids=[indicator_run],
        asset_location_id=assets["A"]["asset_location_id"],
        compound_run_id=compound_run,
    )
    assert selection["compound_run_id"] == compound_run
    metric = report["cross_asset_portfolio"]["cross_asset_metrics"][0]
    assert metric["denominator"] == 2
    assert metric["value"] == 0.5


def test_portfolio_adapter_blocks_mixed_currency_without_fx_vintage(tmp_path):
    root, source, assets = _workspace(tmp_path)
    indicator_run = _successful_indicator_run(root, source, assets)
    with connect_catalog(root) as conn:
        rows = [
            ("PX1", "INTERNAL", "P1", "E1", "B1", assets["A"]["asset_location_id"], "EAD", 100.0, "BDT", "2026-09-24", "{}"),
            ("PX2", "INTERNAL", "P1", "E2", "B2", assets["B"]["asset_location_id"], "EAD", 20.0, "USD", "2026-09-24", "{}"),
        ]
        conn.executemany(
            """
            INSERT INTO portfolio_exposure(
                portfolio_exposure_id,tenant_key,portfolio_id,exposure_id,
                borrower_id,asset_location_id,exposure_type,amount,currency,
                valuation_date,metadata_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            rows,
        )
        conn.commit()

    with pytest.raises(ValueError, match="multiple currencies"):
        build_private_decision_workspace(
            root,
            scope_type="PORTFOLIO",
            tenant_key="INTERNAL",
            indicator_run_ids=[indicator_run],
            portfolio_id="P1",
        )


def test_portfolio_adapter_calculates_transparent_footprint_arithmetic(tmp_path):
    root, source, assets = _workspace(tmp_path)
    indicator_run = _successful_indicator_run(root, source, assets)
    with connect_catalog(root) as conn:
        conn.executemany(
            """
            INSERT INTO portfolio_exposure(
                portfolio_exposure_id,tenant_key,portfolio_id,exposure_id,
                borrower_id,asset_location_id,exposure_type,amount,currency,
                valuation_date,metadata_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            [
                ("PX1", "INTERNAL", "P1", "E1", "B1", assets["A"]["asset_location_id"], "EAD", 100.0, "BDT", "2026-09-24", "{}"),
                ("PX2", "INTERNAL", "P1", "E2", "B2", assets["B"]["asset_location_id"], "EAD", 300.0, "BDT", "2026-09-24", "{}"),
            ],
        )
        conn.commit()

    report, _ = build_private_decision_workspace(
        root,
        scope_type="PORTFOLIO",
        tenant_key="INTERNAL",
        indicator_run_ids=[indicator_run],
        portfolio_id="P1",
    )
    metrics = {
        row["metric_id"]: row
        for row in report["cross_asset_portfolio"]["portfolio_metrics"]
    }
    share = metrics["ead_share_in_flood_rp100_depth_m_footprint"]
    assert share["value"] == pytest.approx(0.25)
    assert share["denominator_count"] == 2
    assert share["classification"] == "PORTFOLIO_CONCENTRATION"


def test_output_writer_refuses_uninitialized_root(tmp_path):
    with pytest.raises(ValueError, match="initialized private workspace"):
        build_private_decision_workspace(
            tmp_path / "not_private",
            scope_type="ASSET",
            tenant_key="INTERNAL",
            indicator_run_ids=["anything"],
            asset_location_id="A",
        )
