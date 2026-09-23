import pytest
from clr.product_output import asset_intelligence_report, portfolio_intelligence_report


def test_asset_report_preserves_provenance_and_no_score():
    report = asset_intelligence_report(
        {"external_id":"SYNTH_A","asset_type":"FACTORY","sector":"RMG","site_identity_grade":"EXACT_SITE","coordinate_status":"RESOLVED"},
        [{
            "indicator_id":"flood_rp100_depth_m","label":"RP100 flood depth","value":0.6,"unit":"m",
            "value_class":"SOURCE","measurement_basis":"HYDROLOGICAL_HYDRODYNAMIC_MODEL",
            "source_id":"JRC_RP100","source_vintage":"SYNTH_VINTAGE","quality_flag":"OK"
        }],
        findings=[{"level":"SECOND_ORDER_EXPOSURE","text":"Synthetic finding."}],
    )
    assert report["report_type"] == "ASSET_INTELLIGENCE"
    assert report["direct_evidence"][0]["source_id"] == "JRC_RP100"
    assert "risk_score" not in report
    assert any("No arbitrary composite" in x for x in report["guardrails"])


def test_null_indicator_requires_reason():
    with pytest.raises(ValueError):
        asset_intelligence_report(
            {"external_id":"SYNTH_A"},
            [{
                "indicator_id":"heat","value":None,"value_class":"CALCULATED",
                "measurement_basis":"CALCULATED_FROM_REANALYSIS","source_id":"ERA5L_DAILY",
                "source_vintage":"SYNTH_VINTAGE"
            }]
        )


def test_portfolio_report_blocks_ungoverned_pd_loss_class():
    with pytest.raises(ValueError):
        portfolio_intelligence_report(
            "SYNTH_PORTFOLIO",
            [{"metric_id":"pd_change","value":0.03,"classification":"PREDICTED_PD"}]
        )


def test_portfolio_report_accepts_exposure_metric():
    report = portfolio_intelligence_report(
        "SYNTH_PORTFOLIO",
        [{"metric_id":"ead_share_in_rp100_footprint","value":0.25,"unit":"share","classification":"BANK_CONCENTRATION"}],
        missing_data_questions=["Add exact collateral coordinates."],
    )
    assert report["portfolio_metrics"][0]["value"] == 0.25
    assert report["what_data_would_change_the_answer"] == ["Add exact collateral coordinates."]
