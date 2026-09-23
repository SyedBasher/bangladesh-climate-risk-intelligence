from __future__ import annotations
import pandas as pd

def _require_cols(df, cols):
    missing=set(cols)-set(df.columns)
    if missing: raise ValueError(f"Missing required columns: {sorted(missing)}")

def _nonnegative(series,name):
    x=pd.to_numeric(series,errors="coerce")
    if (x.dropna()<0).any(): raise ValueError(f"{name} contains negative values")
    return x

def currency_guard(df,currency_col="currency"):
    vals=set(df[currency_col].dropna().astype(str))
    if len(vals)>1: raise ValueError("Multiple currencies present. Convert with an explicit FX vintage before aggregation.")
    return next(iter(vals)) if vals else None

def exposure_in_footprint(df,exposure_col,depth_col,id_col=None):
    _require_cols(df,[exposure_col,depth_col]); exp=_nonnegative(df[exposure_col],exposure_col); depth=pd.to_numeric(df[depth_col],errors="coerce")
    valid=exp.notna() & depth.notna(); total=float(exp[valid].sum()); hit=valid & (depth>0); exposed=float(exp[hit].sum())
    return {"valid_exposure_total":total,"exposure_in_footprint":exposed,"exposure_share_in_footprint":None if total==0 else exposed/total,"n_valid":int(valid.sum()),"n_exposed":int(hit.sum()),"exposed_ids":[] if id_col is None else df.loc[hit,id_col].astype(str).tolist()}

def hhi_from_exposures(values):
    x=pd.to_numeric(pd.Series(values),errors="coerce").dropna()
    if (x<0).any(): raise ValueError("Negative exposures are not allowed")
    total=float(x.sum())
    if total<=0: return None
    shares=x/total; return float((shares**2).sum())

def exposed_ead_hhi(df,borrower_col="borrower_id",ead_col="ead",depth_col="flood_rp100_depth_m"):
    _require_cols(df,[borrower_col,ead_col,depth_col]); x=df.copy(); x[ead_col]=_nonnegative(x[ead_col],ead_col); x[depth_col]=pd.to_numeric(x[depth_col],errors="coerce")
    x=x[(x[depth_col]>0)&x[ead_col].notna()]
    if x.empty: return None
    return hhi_from_exposures(x.groupby(borrower_col,dropna=False)[ead_col].sum().values)

def borrower_site_exposure_share(df,borrower_id,depth_col="flood_rp100_depth_m",asset_role_col="asset_role"):
    _require_cols(df,["borrower_id",depth_col,asset_role_col]); x=df[(df["borrower_id"]==borrower_id)&(df[asset_role_col]=="OPERATING_SITE")].copy(); depth=pd.to_numeric(x[depth_col],errors="coerce"); valid=depth.notna()
    return None if valid.sum()==0 else float((depth[valid]>0).sum()/valid.sum())

def borrower_capacity_exposure_share(df,borrower_id,depth_col="flood_rp100_depth_m",capacity_col="annual_capacity"):
    _require_cols(df,["borrower_id",depth_col,capacity_col]); x=df[df["borrower_id"]==borrower_id].copy(); depth=pd.to_numeric(x[depth_col],errors="coerce"); cap=_nonnegative(x[capacity_col],capacity_col); valid=depth.notna()&cap.notna(); total=float(cap[valid].sum())
    return None if total==0 else float(cap[valid & (depth>0)].sum()/total)

def operating_collateral_mismatch(operating_depths,collateral_depths):
    op=pd.to_numeric(pd.Series(operating_depths),errors="coerce").dropna(); col=pd.to_numeric(pd.Series(collateral_depths),errors="coerce").dropna()
    if op.empty or col.empty: return None
    return bool((op>0).any()) != bool((col>0).any())

def aggregate_by_cell(df,value_col,cell_col):
    _require_cols(df,[value_col,cell_col]); x=df[[value_col,cell_col]].copy(); x[value_col]=_nonnegative(x[value_col],value_col); x=x.dropna(); return x.groupby(cell_col,as_index=False)[value_col].sum().sort_values(value_col,ascending=False)

def common_bottleneck_exposure(route_links,exposure_col="ead",edge_col="edge_id",exposed_col="hazard_exposed"):
    _require_cols(route_links,[edge_col,exposure_col,exposed_col]); x=route_links.copy(); x[exposure_col]=_nonnegative(x[exposure_col],exposure_col); x=x[(x[exposed_col]==True)&x[exposure_col].notna()]
    if x.empty: return pd.DataFrame(columns=[edge_col,"asset_count",exposure_col])
    out=x.groupby(edge_col).agg(asset_count=(edge_col,"size"),**{exposure_col:(exposure_col,"sum")}).reset_index(); return out.sort_values([exposure_col,"asset_count"],ascending=[False,False])

def bb_regulatory_sensitivity(climate_vulnerable_loans,downgrade_share):
    base=float(climate_vulnerable_loans); rate=float(downgrade_share)
    if base<0 or not (0<=rate<=1): raise ValueError("Invalid scenario inputs")
    return {"climate_vulnerable_loans":base,"downgrade_share":rate,"direct_downgrade_amount":base*rate,"classification":"OFFICIAL_REGULATORY_SCENARIO_ARITHMETIC"}

def data_quality_summary(loans,assets,links):
    _require_cols(loans,["loan_id","borrower_id","ead","currency"]); _require_cols(assets,["asset_id","borrower_id","latitude","longitude","site_identity_grade","coordinate_status"]); _require_cols(links,["loan_id","asset_id"])
    loan_ids=set(loans["loan_id"].astype(str)); asset_ids=set(assets["asset_id"].astype(str)); linked_loans=set(links["loan_id"].astype(str)); linked_assets=set(links["asset_id"].astype(str)); exact_resolved=((assets["site_identity_grade"]=="EXACT_SITE")&(assets["coordinate_status"]=="RESOLVED")).sum()
    return {"loan_count":int(len(loans)),"asset_count":int(len(assets)),"loan_share_with_asset_link":0 if not loan_ids else len(loan_ids&linked_loans)/len(loan_ids),"asset_share_linked_to_loan":0 if not asset_ids else len(asset_ids&linked_assets)/len(asset_ids),"asset_share_exact_resolved":0 if len(assets)==0 else float(exact_resolved/len(assets)),"missing_ead_share":float(loans["ead"].isna().mean()) if len(loans) else 0}
