import pandas as pd
from clr.intelligence import worker_heat_exposure_days, workers_at_flooded_return_period_site, portfolio_footprint_exposure, route_exposed_share, pareto_compare, evidence_safe_narrative

def test_worker_heat_exposure_is_arithmetic(): assert worker_heat_exposure_days(1500,24)==36000

def test_workers_in_modelled_flood_footprint():
    assert workers_at_flooded_return_period_site(1000,0.5)==1000
    assert workers_at_flooded_return_period_site(1000,0.0)==0

def test_portfolio_exposure_no_loss_model():
    df=pd.DataFrame({"ead":[100,200,300],"depth":[0.0,0.4,1.2]})
    r=portfolio_footprint_exposure(df,"ead","depth")
    assert r["exposure_in_footprint"]==500
    assert abs(r["exposure_share_in_footprint"]-5/6)<1e-12

def test_route_exposed_share(): assert route_exposed_share(10,2.5)==0.25

def test_pareto_dominance_without_weights():
    r=pareto_compare({"flood":0.2,"heat":20,"water":2},{"flood":0.5,"heat":25,"water":2},{"flood":True,"heat":True,"water":True})
    assert r["a_dominates_b"] and not r["b_dominates_a"]

def test_pareto_tradeoff_no_winner():
    r=pareto_compare({"flood":0.2,"heat":30},{"flood":0.5,"heat":20},{"flood":True,"heat":True})
    assert not r["a_dominates_b"] and not r["b_dominates_a"]

def test_narrative_guardrail():
    out=evidence_safe_narrative({"worker_total":1500,"days_tmax_gt_35c":24,"flood_rp100_depth_m":0.6})
    txt=" ".join(x["text"]+" "+x["guardrail"] for x in out).lower()
    assert "worker-heat exposure days" in txt
    assert "not estimated lost workdays" in txt
    assert "no pd" in txt
