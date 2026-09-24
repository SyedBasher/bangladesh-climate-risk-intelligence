import pytest

from clr.decision_reports import decision_workspace_report
from clr.product_output import (
    asset_intelligence_report,
    compound_intelligence_report,
    portfolio_intelligence_report,
)


def _asset_report():
    return asset_intelligence_report(
        {
            "external_id": "SYNTH_A",
            "asset_type": "FACTORY",
            "sector": "RMG",
            "site_identity_grade": "EXACT_SITE",
            "coordinate_status": "RESOLVED",
        },
        [
            {
                "indicator_id": "flood_rp100_depth_m",
                "label": "RP100 flood depth",
                "value": 0.4,
                "unit": "m",
                "value_class": "SOURCE",
                "measurement_basis": "HYDROLOGICAL_HYDRODYNAMIC_MODEL",
                "source_id": "JRC_RP100",
                "source_vintage": "SYNTH_VINTAGE",
                "quality_flag": "OK",
            }
        ],
        findings=[
            {
                "level": "SECOND_ORDER_EXPOSURE",
                "finding_id": "SYNTH_WORKER_HEAT",
                "text": "Synthetic exposure arithmetic.",
                "guardrail": "Not estimated productivity loss.",
            },
            {
                "level": "THIRD_ORDER_QUESTION",
                "finding_id": "SYNTH_DATA_QUESTION",
                "text": "Synthetic operational question.",
                "guardrail": "No loss estimate.",
            },
        ],
        missing_data_questions=["Add workforce by shift."],
    )


def _compound_report():
    return compound_intelligence_report(
        "INTERNAL",
        2025,
        100,
        asset_compound_evidence=[
            {
                "external_id": "SYNTH_A",
                "evidence_state": "SITE_AND_ROUTE_EXPOSED",
            }
        ],
        cross_asset_metrics=[
            {
                "analysis_type": "SITE_ROUTE_FLOOD",
                "metric_id": "rp100_asset_share_site_and_route_exposed",
                "value": 0.5,
                "unit": "share",
                "denominator": 4,
                "quality_flag": "OK",
            }
        ],
        shared_bottlenecks=[
            {
                "physical_edge_key": "SYNTH_EDGE",
                "distinct_asset_count": 2,
            }
        ],
        input_manifest={"inputs": [{"dataset_name": "synthetic"}]},
    )


def _portfolio_report():
    return portfolio_intelligence_report(
        "SYNTH_PORTFOLIO",
        [
            {
                "metric_id": "ead_share_in_rp100_footprint",
                "value": 0.25,
                "unit": "share",
                "classification": "BANK_CONCENTRATION",
                "source_vintage": "SYNTH_VINTAGE",
                "quality_flag": "OK",
            }
        ],
        missing_data_questions=["Add exact collateral coordinates."],
    )


def test_decision_workspace_assembles_governed_modules_without_score():
    report = decision_workspace_report(
        scope_type="PORTFOLIO",
        tenant_scope="INTERNAL",
        subject_id="SYNTH_PORTFOLIO",
        asset_report=_asset_report(),
        compound_report=_compound_report(),
        portfolio_report=_portfolio_report(),
        executive_summary=[
            {
                "statement_id": "S1",
                "text": "Synthetic evidence statement.",
                "evidence_class": "COMPOUND",
                "source_refs": ["COMPOUND_CROSS_ASSET_INTELLIGENCE"],
                "guardrail": "Synthetic example only.",
            }
        ],
        data_readiness={"source_completeness": "SYNTHETIC_COMPLETE"},
        logistics_dependencies=[
            {
                "dependency_id": "SYNTH_PORT_ROUTE",
                "evidence_state": "ROUTE_EXPOSED",
                "guardrail": "Exposure does not establish closure.",
            }
        ],
        missing_data=[
            {
                "data_item": "Add floor and equipment elevation.",
                "why_it_matters": "Separates site hazard from equipment exposure.",
                "decision_question": "Could water reach critical equipment?",
            }
        ],
    )

    assert report["report_type"] == "DECISION_PORTFOLIO_WORKSPACE"
    assert report["scope"]["scope_type"] == "PORTFOLIO"
    assert report["data_readiness"]["site_identity_grade"] == "EXACT_SITE"
    assert report["direct_physical_evidence"][0]["source_id"] == "JRC_RP100"
    assert len(report["second_order_exposure"]) == 1
    assert len(report["operational_transmission"]) == 1
    assert report["cross_asset_portfolio"]["cross_asset_metrics"][0]["denominator"] == 4
    assert report["cross_asset_portfolio"]["portfolio_metrics"][0]["value"] == 0.25
    assert report["evidence_provenance"][0]["input_manifest"]["inputs"][0]["dataset_name"] == "synthetic"
    assert "risk_score" not in str(report)
    assert any("No overall or composite" in x for x in report["guardrails"])


def test_decision_workspace_requires_source_refs_for_evidence_summary():
    with pytest.raises(ValueError):
        decision_workspace_report(
            scope_type="ASSET",
            tenant_scope="INTERNAL",
            subject_id="SYNTH_A",
            asset_report=_asset_report(),
            executive_summary=[
                {
                    "statement_id": "S1",
                    "text": "Unsupported statement.",
                    "evidence_class": "DIRECT",
                    "source_refs": [],
                }
            ],
        )


def test_decision_workspace_requires_denominator_for_share_metric():
    compound = _compound_report()
    compound["cross_asset_metrics"][0].pop("denominator")
    with pytest.raises(ValueError):
        decision_workspace_report(
            scope_type="PORTFOLIO",
            tenant_scope="INTERNAL",
            subject_id="SYNTH_PORTFOLIO",
            compound_report=compound,
        )


def test_decision_workspace_blocks_ungoverned_pd_lgd_loss_metric():
    portfolio = _portfolio_report()
    portfolio["portfolio_metrics"].append(
        {
            "metric_id": "synthetic_pd",
            "value": 0.03,
            "classification": "PREDICTED_PD",
        }
    )
    with pytest.raises(ValueError):
        decision_workspace_report(
            scope_type="PORTFOLIO",
            tenant_scope="INTERNAL",
            subject_id="SYNTH_PORTFOLIO",
            portfolio_report=portfolio,
        )


def test_decision_workspace_requires_null_reason_for_direct_evidence():
    asset = _asset_report()
    asset["direct_evidence"][0]["value"] = None
    asset["direct_evidence"][0]["null_reason"] = None
    with pytest.raises(ValueError):
        decision_workspace_report(
            scope_type="ASSET",
            tenant_scope="INTERNAL",
            subject_id="SYNTH_A",
            asset_report=asset,
        )


def test_missing_data_is_structured_and_deduplicated():
    report = decision_workspace_report(
        scope_type="ASSET",
        tenant_scope="INTERNAL",
        subject_id="SYNTH_A",
        asset_report=_asset_report(),
        missing_data=["Add workforce by shift.", "Add cooling and backup power."],
    )
    items = [x["data_item"] for x in report["what_data_would_change_the_answer"]]
    assert items.count("Add workforce by shift.") == 1
    assert "Add cooling and backup power." in items
