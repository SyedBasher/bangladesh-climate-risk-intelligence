import pandas as pd
import pytest
from clr.portfolio import currency_guard, exposure_in_footprint, hhi_from_exposures, exposed_ead_hhi, borrower_site_exposure_share, borrower_capacity_exposure_share, operating_collateral_mismatch, aggregate_by_cell, common_bottleneck_exposure, bb_regulatory_sensitivity, data_quality_summary
from clr.portfolio_intelligence import portfolio_next_data_questions, bounded_portfolio_findings

def test_exposure_in_footprint():
    df=pd.DataFrame({"id":["a","b","c"],"ead":[100,200,300],"depth":[0,0.4,1.2]})
    r=exposure_in_footprint(df,"ead","depth","id")
    assert r["exposure_in_footprint"]==500 and abs(r["exposure_share_in_footprint"]-5/6)<1e-12

def test_hhi(): assert abs(hhi_from_exposures([50,50])-0.5)<1e-12

def test_exposed_ead_hhi_by_borrower():
    df=pd.DataFrame({"borrower_id":["B1","B1","B2"],"ead":[50,50,100],"flood_rp100_depth_m":[1,1,1]})
    assert abs(exposed_ead_hhi(df)-0.5)<1e-12

def test_borrower_site_share():
    df=pd.DataFrame({"borrower_id":["B1","B1"],"asset_role":["OPERATING_SITE","OPERATING_SITE"],"flood_rp100_depth_m":[1,0]})
    assert borrower_site_exposure_share(df,"B1")==0.5

def test_capacity_share():
    df=pd.DataFrame({"borrower_id":["B1","B1"],"flood_rp100_depth_m":[1,0],"annual_capacity":[300,700]})
    assert borrower_capacity_exposure_share(df,"B1")==0.3

def test_operating_collateral_mismatch():
    assert operating_collateral_mismatch([0],[1]) is True and operating_collateral_mismatch([1],[1]) is False

def test_cell_aggregation():
    out=aggregate_by_cell(pd.DataFrame({"cell":["C1","C1","C2"],"ead":[100,200,50]}),"ead","cell")
    assert out.iloc[0]["ead"]==300

def test_bottleneck_exposure():
    out=common_bottleneck_exposure(pd.DataFrame({"edge_id":["E1","E1","E2"],"ead":[100,200,300],"hazard_exposed":[True,True,False]}))
    assert len(out)==1 and out.iloc[0]["ead"]==300

def test_bb_regulatory_scenario_arithmetic():
    r=bb_regulatory_sensitivity(1000,0.06)
    assert r["direct_downgrade_amount"]==60 and r["classification"]=="OFFICIAL_REGULATORY_SCENARIO_ARITHMETIC"

def test_mixed_currency_blocked():
    with pytest.raises(ValueError): currency_guard(pd.DataFrame({"currency":["BDT","USD"]}))

def test_data_quality_and_questions():
    loans=pd.DataFrame({"loan_id":["L1","L2"],"borrower_id":["B1","B2"],"ead":[100,None],"currency":["BDT","BDT"]})
    assets=pd.DataFrame({"asset_id":["A1","A2"],"borrower_id":["B1","B2"],"latitude":[1,2],"longitude":[3,4],"site_identity_grade":["EXACT_SITE","PROBABLE_SITE"],"coordinate_status":["RESOLVED","RESOLVED"]})
    links=pd.DataFrame({"loan_id":["L1"],"asset_id":["A1"]})
    s=data_quality_summary(loans,assets,links); q=portfolio_next_data_questions(s)
    assert s["loan_share_with_asset_link"]==0.5 and s["asset_share_exact_resolved"]==0.5 and any("geocoding" in x.lower() for x in q)

def test_bounded_findings_do_not_claim_loss():
    out=bounded_portfolio_findings({"ead_share_in_rp100_footprint":0.25,"hazard_exposed_ead_hhi":0.4})
    txt=" ".join(x["text"]+" "+x["guardrail"] for x in out).lower()
    assert "not a probability of default" in txt and "not a climate-risk score" in txt
