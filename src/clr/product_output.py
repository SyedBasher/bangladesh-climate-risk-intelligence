from __future__ import annotations

from typing import Any

REQUIRED_INDICATOR_FIELDS = {
    "indicator_id", "value_class", "measurement_basis", "source_id", "source_vintage"
}


def _clean_indicator(row: dict[str, Any]) -> dict[str, Any]:
    missing = REQUIRED_INDICATOR_FIELDS - set(row)
    if missing:
        raise ValueError(f"Indicator missing required provenance fields: {sorted(missing)}")
    value = row.get("value")
    null_reason = row.get("null_reason")
    if value is None and not null_reason:
        raise ValueError("Null indicator values require null_reason")
    return {
        "indicator_id": row["indicator_id"],
        "label": row.get("label", row["indicator_id"]),
        "value": value,
        "unit": row.get("unit"),
        "value_class": row["value_class"],
        "measurement_basis": row["measurement_basis"],
        "source_id": row["source_id"],
        "source_vintage": row["source_vintage"],
        "quality_flag": row.get("quality_flag", "OK"),
        "null_reason": null_reason,
        "period_start": row.get("period_start"),
        "period_end": row.get("period_end"),
        "method_version": row.get("method_version"),
    }


def asset_intelligence_report(
    asset: dict[str, Any],
    indicators: list[dict[str, Any]],
    findings: list[dict[str, Any]] | None = None,
    evidence: list[dict[str, Any]] | None = None,
    missing_data_questions: list[str] | None = None,
) -> dict[str, Any]:
    """Build a bounded asset-level product payload with no composite risk score."""
    cleaned = [_clean_indicator(x) for x in indicators]
    return {
        "report_type": "ASSET_INTELLIGENCE",
        "schema_version": "0.1.0",
        "asset": {
            "external_id": asset.get("external_id"),
            "asset_type": asset.get("asset_type"),
            "sector": asset.get("sector"),
            "site_identity_grade": asset.get("site_identity_grade"),
            "coordinate_status": asset.get("coordinate_status"),
        },
        "direct_evidence": cleaned,
        "analytical_findings": findings or [],
        "evidence_panel": evidence or [],
        "what_data_would_change_the_answer": missing_data_questions or [],
        "guardrails": [
            "No arbitrary composite climate-risk score is calculated.",
            "Hazard exposure is not automatically converted into damage, downtime, PD/LGD, collateral haircut, or insurance loss.",
            "Observed, modelled, reanalysis, and calculated values remain separately labelled.",
        ],
    }


def portfolio_intelligence_report(
    portfolio_id: str,
    metrics: list[dict[str, Any]],
    findings: list[dict[str, Any]] | None = None,
    evidence: list[dict[str, Any]] | None = None,
    missing_data_questions: list[str] | None = None,
) -> dict[str, Any]:
    """Build a bounded portfolio-level product payload."""
    for metric in metrics:
        if "metric_id" not in metric or "value" not in metric:
            raise ValueError("Portfolio metrics require metric_id and value")
        if metric.get("classification") in {"EXPECTED_LOSS", "PREDICTED_PD", "PREDICTED_LGD"}:
            raise ValueError("Loss/PD/LGD outputs require a separately governed model, not the base product layer")
    return {
        "report_type": "PORTFOLIO_INTELLIGENCE",
        "schema_version": "0.1.0",
        "portfolio_id": portfolio_id,
        "portfolio_metrics": metrics,
        "analytical_findings": findings or [],
        "evidence_panel": evidence or [],
        "what_data_would_change_the_answer": missing_data_questions or [],
        "guardrails": [
            "Portfolio concentration is not expected loss.",
            "Regulatory sensitivity scenarios are displayed separately from Mangrove-calculated exposure metrics.",
            "No borrower-level risk score is created by default.",
        ],
    }



def compound_intelligence_report(
    tenant_scope: str,
    year: int,
    return_period: int,
    asset_compound_evidence: list[dict[str, Any]],
    cross_asset_metrics: list[dict[str, Any]],
    shared_bottlenecks: list[dict[str, Any]],
    input_manifest: dict[str, Any],
) -> dict[str, Any]:
    """Build a transparent compound/cross-asset payload with explicit denominators."""
    if not str(tenant_scope).strip():
        raise ValueError("tenant_scope must be non-empty")
    if int(return_period) <= 0:
        raise ValueError("return_period must be positive")

    cleaned_metrics=[]
    for metric in cross_asset_metrics:
        if "metric_id" not in metric or "value" not in metric:
            raise ValueError("Cross-asset metrics require metric_id and value")
        value=metric.get("value")
        quality=metric.get("quality_flag","OK")
        if value is None and quality=="OK":
            raise ValueError("Null cross-asset metric requires a non-OK quality_flag")
        denominator=metric.get("denominator")
        if denominator is not None and int(denominator)<0:
            raise ValueError("denominator cannot be negative")
        cleaned_metrics.append({
            "analysis_type":metric.get("analysis_type"),
            "metric_id":metric["metric_id"],
            "value":value,
            "unit":metric.get("unit"),
            "denominator":None if denominator is None else int(denominator),
            "quality_flag":quality,
            "period_start":metric.get("period_start"),
            "period_end":metric.get("period_end"),
        })

    return {
        "report_type":"COMPOUND_CROSS_ASSET_INTELLIGENCE",
        "schema_version":"0.1.0",
        "tenant_scope":str(tenant_scope),
        "year":int(year),
        "return_period":int(return_period),
        "asset_compound_evidence":asset_compound_evidence,
        "cross_asset_metrics":cleaned_metrics,
        "shared_bottlenecks":shared_bottlenecks,
        "input_manifest":input_manifest,
        "guardrails":[
            "No composite climate-risk score or hidden weighting is calculated.",
            "Heat–drought metrics describe same-month co-occurrence, not economic loss or causal interaction.",
            "Flood-exposed routes are not assumed to be blocked or impassable.",
            "Cross-asset shares use explicit valid-data denominators; incomplete assets are not treated as unexposed.",
            "Metrics are scoped to one tenant and do not combine unrelated customer portfolios.",
        ],
    }
