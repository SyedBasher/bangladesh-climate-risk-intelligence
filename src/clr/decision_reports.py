from __future__ import annotations

import math
from typing import Any

ALLOWED_SCOPE_TYPES = {"ASSET", "PORTFOLIO"}
FORBIDDEN_METRIC_CLASSES = {"EXPECTED_LOSS", "PREDICTED_PD", "PREDICTED_LGD"}
FORBIDDEN_KEYS = {"risk_score", "climate_risk_score", "composite_score", "composite_risk_score"}

_REQUIRED_DIRECT_EVIDENCE_FIELDS = {
    "indicator_id",
    "value_class",
    "measurement_basis",
    "source_id",
    "source_vintage",
    "quality_flag",
}


def _require_nonempty(value: Any, name: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        raise ValueError(f"{name} must be non-empty")
    return text


def _optional_nonnegative_int(value: Any, name: str) -> int | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if math.isnan(numeric):
        return None
    if not math.isfinite(numeric) or numeric != int(numeric):
        raise ValueError(f"{name} must be an integer")
    out = int(numeric)
    if out < 0:
        raise ValueError(f"{name} cannot be negative")
    return out


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _assert_no_forbidden_keys(value: Any, path: str = "report") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in FORBIDDEN_KEYS:
                raise ValueError(f"Forbidden score field at {path}.{key}")
            _assert_no_forbidden_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            _assert_no_forbidden_keys(child, f"{path}[{idx}]")


def _validate_direct_evidence(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for row in rows:
        missing = _REQUIRED_DIRECT_EVIDENCE_FIELDS - set(row)
        if missing:
            raise ValueError(
                f"Direct evidence missing provenance fields: {sorted(missing)}"
            )
        if row.get("value") is None and not row.get("null_reason"):
            raise ValueError("Null direct evidence requires null_reason")
        cleaned.append(dict(row))
    return cleaned


def _validate_summary(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    allowed = {
        "DIRECT",
        "CALCULATED",
        "COMPOUND",
        "OPERATIONAL",
        "CROSS_ASSET",
        "MISSING_DATA",
    }
    out: list[dict[str, Any]] = []
    for row in rows:
        statement_id = _require_nonempty(row.get("statement_id"), "statement_id")
        text = _require_nonempty(row.get("text"), "summary text")
        evidence_class = _require_nonempty(
            row.get("evidence_class"), "evidence_class"
        ).upper()
        if evidence_class not in allowed:
            raise ValueError(f"Unsupported evidence_class: {evidence_class}")
        source_refs = [
            str(x).strip() for x in row.get("source_refs", []) if str(x).strip()
        ]
        if evidence_class != "MISSING_DATA" and not source_refs:
            raise ValueError(
                "Executive evidence statements require source_refs unless "
                "evidence_class is MISSING_DATA"
            )
        out.append(
            {
                "statement_id": statement_id,
                "text": text,
                "evidence_class": evidence_class,
                "source_refs": source_refs,
                "guardrail": row.get("guardrail"),
            }
        )
    return out


def _validate_compound_metrics(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        if "metric_id" not in row or "value" not in row:
            raise ValueError("Cross-asset metrics require metric_id and value")
        quality = row.get("quality_flag", "OK")
        if row.get("value") is None and quality == "OK":
            raise ValueError("Null cross-asset metric requires non-OK quality_flag")
        denominator = _optional_nonnegative_int(
            row.get("denominator"),
            "denominator",
        )
        if str(row.get("unit", "")).lower() == "share" and denominator is None:
            raise ValueError("Share metrics require an explicit denominator")
        cleaned = dict(row)
        if denominator is not None:
            cleaned["denominator"] = denominator
        out.append(cleaned)
    return out


def _validate_portfolio_metrics(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        if "metric_id" not in row or "value" not in row:
            raise ValueError("Portfolio metrics require metric_id and value")
        classification = row.get("classification")
        if classification in FORBIDDEN_METRIC_CLASSES:
            raise ValueError(
                "Expected-loss/PD/LGD outputs require a separately governed model"
            )
        cleaned = dict(row)
        denominator = _optional_nonnegative_int(
            row.get("denominator_count"),
            "denominator_count",
        )
        if denominator is not None:
            cleaned["denominator_count"] = denominator
        if str(row.get("unit", "")).lower() == "share" and denominator is None:
            raise ValueError("Portfolio share metrics require denominator_count")
        out.append(cleaned)
    return out


def _normalize_missing_data(
    rows: list[dict[str, Any] | str],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if isinstance(row, str):
            item = {
                "data_item": row.strip(),
                "why_it_matters": None,
                "decision_question": None,
                "source_module": None,
            }
        else:
            item = {
                "data_item": _require_nonempty(row.get("data_item"), "data_item"),
                "why_it_matters": row.get("why_it_matters"),
                "decision_question": row.get("decision_question"),
                "source_module": row.get("source_module"),
            }
        if item["data_item"] and item["data_item"] not in seen:
            seen.add(item["data_item"])
            out.append(item)
    return out


def _check_module(
    report: dict[str, Any] | None,
    expected_type: str,
    name: str,
) -> dict[str, Any] | None:
    if report is None:
        return None
    if report.get("report_type") != expected_type:
        raise ValueError(
            f"{name} must have report_type={expected_type}"
        )
    return report


def decision_workspace_report(
    *,
    scope_type: str,
    tenant_scope: str,
    subject_id: str,
    asset_report: dict[str, Any] | None = None,
    compound_report: dict[str, Any] | None = None,
    portfolio_report: dict[str, Any] | None = None,
    executive_summary: list[dict[str, Any]] | None = None,
    data_readiness: dict[str, Any] | None = None,
    operational_transmission: list[dict[str, Any]] | None = None,
    logistics_dependencies: list[dict[str, Any]] | None = None,
    evidence_provenance: list[dict[str, Any]] | None = None,
    missing_data: list[dict[str, Any] | str] | None = None,
) -> dict[str, Any]:
    """Assemble existing governed modules into a decision-facing workspace.

    Version 0.1 deliberately does not auto-generate narrative conclusions.
    Executive statements must be supplied with explicit source references.
    """
    scope = _require_nonempty(scope_type, "scope_type").upper()
    if scope not in ALLOWED_SCOPE_TYPES:
        raise ValueError(f"scope_type must be one of {sorted(ALLOWED_SCOPE_TYPES)}")
    tenant = _require_nonempty(tenant_scope, "tenant_scope")
    subject = _require_nonempty(subject_id, "subject_id")

    asset = _check_module(asset_report, "ASSET_INTELLIGENCE", "asset_report")
    compound = _check_module(
        compound_report,
        "COMPOUND_CROSS_ASSET_INTELLIGENCE",
        "compound_report",
    )
    portfolio = _check_module(
        portfolio_report,
        "PORTFOLIO_INTELLIGENCE",
        "portfolio_report",
    )

    direct = _validate_direct_evidence(
        list(asset.get("direct_evidence", [])) if asset else []
    )
    findings = list(asset.get("analytical_findings", [])) if asset else []
    second_order = [
        dict(row)
        for row in findings
        if str(row.get("level", "")).startswith("SECOND_ORDER")
    ]
    derived_operational = [
        dict(row)
        for row in findings
        if not str(row.get("level", "")).startswith("SECOND_ORDER")
    ]
    derived_operational.extend(dict(x) for x in (operational_transmission or []))

    compound_asset = (
        [dict(x) for x in compound.get("asset_compound_evidence", [])]
        if compound
        else []
    )
    compound_metrics = _validate_compound_metrics(
        list(compound.get("cross_asset_metrics", [])) if compound else []
    )
    shared_bottlenecks = (
        [dict(x) for x in compound.get("shared_bottlenecks", [])]
        if compound
        else []
    )
    portfolio_metrics = _validate_portfolio_metrics(
        list(portfolio.get("portfolio_metrics", [])) if portfolio else []
    )

    readiness = dict(data_readiness or {})
    if asset:
        asset_identity = asset.get("asset", {})
        readiness.setdefault(
            "site_identity_grade", asset_identity.get("site_identity_grade")
        )
        readiness.setdefault(
            "coordinate_status", asset_identity.get("coordinate_status")
        )

    provenance = [dict(x) for x in (evidence_provenance or [])]
    if compound:
        provenance.append(
            {
                "source_module": "COMPOUND_CROSS_ASSET_INTELLIGENCE",
                "input_manifest": compound.get("input_manifest", {}),
            }
        )

    missing_rows: list[dict[str, Any] | str] = list(missing_data or [])
    for module_name, module in [
        ("ASSET_INTELLIGENCE", asset),
        ("PORTFOLIO_INTELLIGENCE", portfolio),
    ]:
        if module:
            for question in module.get("what_data_would_change_the_answer", []):
                missing_rows.append(
                    {
                        "data_item": question,
                        "source_module": module_name,
                    }
                )

    module_meta = []
    for module in [asset, compound, portfolio]:
        if module:
            module_meta.append(
                {
                    "report_type": module["report_type"],
                    "schema_version": module.get("schema_version"),
                }
            )

    guardrails = [
        "No overall or composite climate-risk score is calculated.",
        "Hazard and exposure evidence are not automatically converted into damage, downtime, PD, LGD, expected loss, or insurance loss.",
        "Observed, modelled, reanalysis, and calculated quantities remain separately labelled.",
        "Route hazard exposure does not establish road closure or impassability.",
        "Population context is not factory workforce, and built-up context is not property value.",
        "Compound evidence is not a weighted index or causal economic multiplier.",
    ]
    for module in [asset, compound, portfolio]:
        if module:
            guardrails.extend(module.get("guardrails", []))

    report = {
        "report_type": "DECISION_PORTFOLIO_WORKSPACE",
        "schema_version": "0.1.0",
        "scope": {
            "scope_type": scope,
            "tenant_scope": tenant,
            "subject_id": subject,
        },
        "executive_evidence_summary": _validate_summary(executive_summary or []),
        "data_readiness": readiness,
        "direct_physical_evidence": direct,
        "second_order_exposure": second_order,
        "compound_evidence": compound_asset,
        "operational_transmission": derived_operational,
        "logistics_dependencies": [
            dict(x) for x in (logistics_dependencies or [])
        ],
        "cross_asset_portfolio": {
            "cross_asset_metrics": compound_metrics,
            "shared_bottlenecks": shared_bottlenecks,
            "portfolio_metrics": portfolio_metrics,
        },
        "evidence_provenance": provenance,
        "what_data_would_change_the_answer": _normalize_missing_data(missing_rows),
        "source_modules": module_meta,
        "guardrails": _dedupe_strings(guardrails),
    }
    _assert_no_forbidden_keys(report)
    return report
