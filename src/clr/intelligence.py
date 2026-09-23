from __future__ import annotations
import pandas as pd

def _nonnegative(x,name):
    if x is None or pd.isna(x): return None
    x=float(x)
    if x<0: raise ValueError(f"{name} must be nonnegative")
    return x

def worker_heat_exposure_days(workers,heat_days):
    w=_nonnegative(workers,"workers"); d=_nonnegative(heat_days,"heat_days")
    return None if w is None or d is None else w*d

def workers_at_flooded_return_period_site(workers,flood_depth_m):
    w=_nonnegative(workers,"workers")
    if w is None or flood_depth_m is None or pd.isna(flood_depth_m): return None
    depth=float(flood_depth_m)
    if depth<0: raise ValueError("flood depth cannot be negative")
    return w if depth>0 else 0.0

def portfolio_footprint_exposure(df,exposure_col,depth_col):
    if exposure_col not in df or depth_col not in df: raise ValueError("missing required portfolio columns")
    x=df[[exposure_col,depth_col]].copy()
    if x[exposure_col].dropna().lt(0).any(): raise ValueError("negative financial exposure")
    valid=x.dropna(); total=float(valid[exposure_col].sum()); exposed=float(valid.loc[valid[depth_col]>0,exposure_col].sum())
    return {"valid_exposure_total":total,"exposure_in_footprint":exposed,"exposure_share_in_footprint":None if total==0 else exposed/total,"n_valid":int(len(valid)),"n_exposed":int((valid[depth_col]>0).sum())}

def route_exposed_share(total_route_km,exposed_route_km):
    total=_nonnegative(total_route_km,"total_route_km"); exposed=_nonnegative(exposed_route_km,"exposed_route_km")
    if total in (None,0): return None
    if exposed>total+1e-9: raise ValueError("exposed route length cannot exceed total route length")
    return exposed/total

def pareto_compare(a,b,lower_is_better):
    comparable=[]; missing=[]; a_better=[]; b_better=[]; ties=[]
    for metric,lower in lower_is_better.items():
        av=a.get(metric); bv=b.get(metric)
        if av is None or bv is None or pd.isna(av) or pd.isna(bv): missing.append(metric); continue
        av=float(av); bv=float(bv); comparable.append(metric)
        if av==bv: ties.append(metric)
        elif (av<bv and lower) or (av>bv and not lower): a_better.append(metric)
        else: b_better.append(metric)
    return {"a_dominates_b":bool(comparable) and not b_better and bool(a_better),"b_dominates_a":bool(comparable) and not a_better and bool(b_better),"a_better_metrics":a_better,"b_better_metrics":b_better,"ties":ties,"missing":missing,"comparable_metrics":comparable}

def evidence_safe_narrative(asset):
    out=[]; workers=asset.get("worker_total"); heat=asset.get("days_tmax_gt_35c"); depth=asset.get("flood_rp100_depth_m")
    wh=worker_heat_exposure_days(workers,heat)
    if wh is not None:
        out.append({"level":"SECOND_ORDER_EXPOSURE","finding_id":"WORKER_HEAT_EXPOSURE","text":f"{int(workers):,} workers × {heat:g} extreme-heat days = {wh:,.0f} worker-heat exposure days.","research_refs":["R007","R008","R011"],"guardrail":"This is exposure arithmetic, not estimated lost workdays or productivity loss."})
    wf=workers_at_flooded_return_period_site(workers,depth)
    if wf is not None and float(depth)>0:
        out.append({"level":"SECOND_ORDER_EXPOSURE","finding_id":"WORKFORCE_IN_RP100_FOOTPRINT","text":f"The site has {int(workers):,} workers and lies within the modelled RP100 inundation footprint (point depth {float(depth):.2f} m).","research_refs":["R001","R013"],"guardrail":"RP100 is a modelled return-period hazard, not a forecast that the site will flood in a particular year."})
    if depth is not None and not pd.isna(depth) and float(depth)>0:
        out.append({"level":"THIRD_ORDER_QUESTION","finding_id":"FINANCIAL_DATA_REQUEST","text":"For lender/insurer analysis, the next variables are EAD/sum insured, collateral value, floor elevation, insurance, borrower cash flow and route accessibility.","research_refs":["R001","R004","R006"],"guardrail":"No PD, LGD, collateral haircut or expected loss is inferred from flood depth alone."})
    return out
