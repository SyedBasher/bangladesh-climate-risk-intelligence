def portfolio_next_data_questions(summary):
    q=[]
    if summary.get("asset_share_exact_resolved",0)<0.9:
        q.append("Improve borrower/collateral geocoding before relying on fine-resolution hazard metrics.")
    if summary.get("loan_share_with_asset_link",0)<0.9:
        q.append("Link more loans to operating sites and/or collateral assets.")
    if summary.get("missing_ead_share",0)>0:
        q.append("Resolve missing EAD/outstanding exposure values.")
    q += [
        "Add collateral market value, valuation date and LTV where collateral loss analysis is required.",
        "Add borrower revenue/cash-flow and sector-specific operating data before estimating credit-loss transmission.",
        "Add insurance coverage/sum insured before evaluating protection gaps.",
        "Add logistics endpoints and alternative routes before estimating common-bottleneck operational concentration."
    ]
    return q

def bounded_portfolio_findings(metrics):
    out=[]
    share=metrics.get("ead_share_in_rp100_footprint")
    if share is not None:
        out.append({"level":"DIRECT_PORTFOLIO_EXPOSURE","text":f"{share:.1%} of valid EAD is linked to assets inside the modelled RP100 flood footprint.","guardrail":"This is a geospatial exposure share, not a probability of default, loss rate, or forecast."})
    hhi=metrics.get("hazard_exposed_ead_hhi")
    if hhi is not None:
        out.append({"level":"CONCENTRATION","text":f"The HHI of borrower EAD within the selected exposed subset is {hhi:.4f}.","guardrail":"HHI describes concentration within the exposed subset; it is not a climate-risk score."})
    return out
