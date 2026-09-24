from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from .decision_report_html import render_decision_workspace_html
from .decision_reports import decision_workspace_report
from .local_store import connect_catalog, sha256_file
from .portfolio import exposure_in_footprint
from .product_output import (
    asset_intelligence_report,
    compound_intelligence_report,
    portfolio_intelligence_report,
)

_SAFE_PART = re.compile(r"[^A-Za-z0-9._=-]+")
_FINANCIAL_EXPOSURE_TYPES = ("EAD", "COLLATERAL_VALUE", "SUM_INSURED")


def _safe_part(value: Any) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError("Empty output path component")
    return _SAFE_PART.sub("_", text)


def _require_private_root(root: str | Path) -> Path:
    root = Path(root).resolve()
    marker = root / ".private-data-root"
    if not marker.exists():
        raise ValueError(
            f"Refusing to write report outside an initialized private workspace: {root}"
        )
    return root


def _json(value: str | None, default: Any) -> Any:
    if value is None:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("Stored JSON metadata is invalid") from exc


def _require_successful_run(conn, run_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM processing_run WHERE run_id=?",
        (run_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Unknown processing run: {run_id}")
    record = dict(row)
    if record["status"] != "SUCCESS":
        raise ValueError(
            f"Processing run {run_id} is {record['status']}; only SUCCESS runs may feed a decision report"
        )
    record["parameters"] = _json(record.get("parameters_json"), {})
    return record


def _require_runs(conn, run_ids: Iterable[str]) -> list[dict[str, Any]]:
    ids = [str(x).strip() for x in run_ids if str(x).strip()]
    if not ids:
        raise ValueError("At least one explicit indicator run ID is required")
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate run IDs are not allowed")
    return [_require_successful_run(conn, run_id) for run_id in ids]


def _require_indicator_runs_for_tenant(
    conn,
    *,
    tenant_key: str,
    run_ids: list[str],
) -> None:
    for run_id in run_ids:
        row = conn.execute(
            """
            SELECT 1
            FROM asset_indicator
            WHERE tenant_key=? AND run_id=?
            LIMIT 1
            """,
            (tenant_key, run_id),
        ).fetchone()
        if row is None:
            raise ValueError(
                f"Indicator run {run_id} has no evidence for tenant {tenant_key}"
            )


def _require_compound_run_for_tenant(
    conn,
    *,
    tenant_key: str,
    run_id: str,
) -> None:
    row = conn.execute(
        """
        SELECT 1
        FROM cross_asset_metric
        WHERE tenant_key=? AND run_id=?
        LIMIT 1
        """,
        (tenant_key, run_id),
    ).fetchone()
    if row is None:
        raise ValueError(
            f"Compound run {run_id} has no cross-asset evidence for tenant {tenant_key}"
        )


def _require_route_run_for_tenant(
    conn,
    *,
    tenant_key: str,
    run_id: str,
) -> None:
    row = conn.execute(
        """
        SELECT 1
        FROM logistics_route_analysis
        WHERE tenant_key=? AND run_id=?
        LIMIT 1
        """,
        (tenant_key, run_id),
    ).fetchone()
    if row is None:
        raise ValueError(
            f"Route run {run_id} has no logistics evidence for tenant {tenant_key}"
        )


def _resolve_asset(
    conn,
    *,
    tenant_key: str,
    asset_location_id: str | None = None,
    external_system: str | None = None,
    external_id: str | None = None,
) -> dict[str, Any]:
    if asset_location_id:
        rows = conn.execute(
            """
            SELECT * FROM asset_location
            WHERE tenant_key=? AND asset_location_id=?
            """,
            (tenant_key, asset_location_id),
        ).fetchall()
    else:
        if not external_system or not external_id:
            raise ValueError(
                "Asset scope requires asset_location_id or both external_system and external_id"
            )
        rows = conn.execute(
            """
            SELECT * FROM asset_location
            WHERE tenant_key=? AND external_system=? AND external_id=?
              AND valid_to IS NULL
            """,
            (tenant_key, external_system, external_id),
        ).fetchall()
    if not rows:
        raise ValueError("No matching asset exists inside the requested tenant")
    if len(rows) != 1:
        raise ValueError("Asset resolution is ambiguous; use asset_location_id explicitly")
    return dict(rows[0])


def _indicator_sources(conn, asset_indicator_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT DISTINCT
            s.source_artifact_id,
            s.source_id,
            s.provider,
            s.provider_version,
            s.retrieved_at,
            s.valid_time_start,
            s.valid_time_end,
            s.sha256,
            s.retrieval_status,
            src.source_role
        FROM (
            SELECT ai.source_artifact_id AS source_artifact_id,
                   'PRIMARY' AS source_role
            FROM asset_indicator ai
            WHERE ai.asset_indicator_id=?
              AND ai.source_artifact_id IS NOT NULL
            UNION
            SELECT ais.source_artifact_id,
                   ais.source_role
            FROM asset_indicator_source ais
            WHERE ais.asset_indicator_id=?
        ) src
        JOIN source_artifact s
          ON s.source_artifact_id=src.source_artifact_id
        ORDER BY s.source_id, src.source_role
        """,
        (asset_indicator_id, asset_indicator_id),
    ).fetchall()
    return [dict(row) for row in rows]


def _source_label(sources: list[dict[str, Any]]) -> tuple[str, str]:
    if not sources:
        return "NO_REGISTERED_SOURCE_LINEAGE", "NOT_AVAILABLE"
    source_ids = sorted({str(x["source_id"]) for x in sources})
    vintages = []
    for row in sources:
        vintage = row.get("provider_version") or row.get("retrieved_at")
        if vintage:
            vintages.append(f"{row['source_id']}:{vintage}")
    return "; ".join(source_ids), "; ".join(sorted(set(vintages))) or "NOT_AVAILABLE"


def _value_from_indicator(row: dict[str, Any]) -> Any:
    if row.get("value_numeric") is not None:
        return row["value_numeric"]
    if row.get("value_text") is not None:
        return row["value_text"]
    return None


def _load_asset_evidence(
    conn,
    *,
    tenant_key: str,
    asset_location_id: str,
    run_ids: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    placeholders = ",".join("?" for _ in run_ids)
    rows = conn.execute(
        f"""
        SELECT ai.*, pr.pipeline_name, pr.pipeline_version, pr.git_commit
        FROM asset_indicator ai
        JOIN processing_run pr ON pr.run_id=ai.run_id
        WHERE ai.tenant_key=?
          AND ai.asset_location_id=?
          AND ai.run_id IN ({placeholders})
        ORDER BY ai.indicator_id, ai.period_start, ai.period_end, ai.asset_indicator_id
        """,
        (tenant_key, asset_location_id, *run_ids),
    ).fetchall()
    if not rows:
        raise ValueError(
            "No asset indicators match the requested tenant, asset and explicit run IDs"
        )

    duplicate_keys: set[tuple[Any, ...]] = set()
    seen: set[tuple[Any, ...]] = set()
    for raw in rows:
        row = dict(raw)
        key = (row["indicator_id"], row.get("period_start"), row.get("period_end"))
        if key in seen:
            duplicate_keys.add(key)
        seen.add(key)
    if duplicate_keys:
        raise ValueError(
            "Selected runs contain overlapping indicator vintages for the same asset: "
            + ", ".join(str(x) for x in sorted(duplicate_keys))
        )

    evidence: list[dict[str, Any]] = []
    provenance: list[dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        sources = _indicator_sources(conn, row["asset_indicator_id"])
        source_id, source_vintage = _source_label(sources)
        quality = row["quality_flag"]
        if not sources and quality == "OK":
            quality = "MISSING_SOURCE_LINEAGE"
        elif quality == "OK" and any(
            source.get("retrieval_status") != "COMPLETE" for source in sources
        ):
            quality = "SOURCE_NOT_COMPLETE"
        evidence.append(
            {
                "indicator_id": row["indicator_id"],
                "label": row["indicator_id"].replace("_", " ").strip().title(),
                "value": _value_from_indicator(row),
                "unit": row.get("unit"),
                "value_class": row["value_class"],
                "measurement_basis": row["measurement_basis"],
                "source_id": source_id,
                "source_vintage": source_vintage,
                "quality_flag": quality,
                "null_reason": row.get("null_reason"),
                "period_start": row.get("period_start"),
                "period_end": row.get("period_end"),
                "method_version": row.get("method_version"),
            }
        )
        provenance.append(
            {
                "source_module": row["pipeline_name"],
                "indicator_id": row["indicator_id"],
                "indicator_run_id": row["run_id"],
                "pipeline_version": row["pipeline_version"],
                "git_commit": row.get("git_commit"),
                "sources": sources,
            }
        )
    return evidence, provenance


def _load_cross_asset_metrics(
    conn,
    *,
    tenant_key: str,
    compound_run_id: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT * FROM cross_asset_metric
        WHERE tenant_key=? AND run_id=?
        ORDER BY analysis_type, metric_id
        """,
        (tenant_key, compound_run_id),
    ).fetchall()
    metrics: list[dict[str, Any]] = []
    merged_manifest: dict[str, Any] = {"metric_manifests": []}
    for raw in rows:
        row = dict(raw)
        manifest = _json(row.get("input_manifest_json"), {})
        merged_manifest["metric_manifests"].append(
            {"metric_id": row["metric_id"], "manifest": manifest}
        )
        metrics.append(
            {
                "analysis_type": row["analysis_type"],
                "metric_id": row["metric_id"],
                "value": row["value_numeric"] if row["value_numeric"] is not None else row["value_text"],
                "unit": row.get("unit"),
                "denominator": manifest.get("denominator"),
                "quality_flag": row["quality_flag"],
                "period_start": row.get("period_start"),
                "period_end": row.get("period_end"),
            }
        )
    return metrics, merged_manifest


def _load_compound_asset_evidence(
    conn,
    *,
    tenant_key: str,
    compound_run_id: str,
    asset_location_ids: list[str] | None,
) -> list[dict[str, Any]]:
    params: list[Any] = [tenant_key, compound_run_id]
    where = ""
    if asset_location_ids:
        placeholders = ",".join("?" for _ in asset_location_ids)
        where = f" AND ai.asset_location_id IN ({placeholders})"
        params.extend(asset_location_ids)
    rows = conn.execute(
        f"""
        SELECT ai.asset_location_id, al.external_system, al.external_id,
               ai.indicator_id, ai.value_numeric, ai.value_text, ai.unit,
               ai.quality_flag, ai.null_reason, ai.method_version,
               ai.period_start, ai.period_end
        FROM asset_indicator ai
        JOIN asset_location al ON al.asset_location_id=ai.asset_location_id
        WHERE ai.tenant_key=? AND ai.run_id=? {where}
        ORDER BY al.external_system, al.external_id, ai.indicator_id
        """,
        tuple(params),
    ).fetchall()
    return [
        {
            "asset_location_id": row["asset_location_id"],
            "external_system": row["external_system"],
            "external_id": row["external_id"],
            "indicator_id": row["indicator_id"],
            "value": row["value_numeric"] if row["value_numeric"] is not None else row["value_text"],
            "unit": row["unit"],
            "quality_flag": row["quality_flag"],
            "null_reason": row["null_reason"],
            "method_version": row["method_version"],
            "period_start": row["period_start"],
            "period_end": row["period_end"],
        }
        for row in rows
    ]


def _registered_parquet_path(
    root: Path,
    conn,
    *,
    dataset_name: str,
    run_id: str,
) -> Path | None:
    rows = conn.execute(
        """
        SELECT * FROM parquet_dataset
        WHERE dataset_name=? AND run_id=?
        ORDER BY created_at DESC
        """,
        (dataset_name, run_id),
    ).fetchall()
    if not rows:
        return None
    if len(rows) != 1:
        raise ValueError(
            f"Ambiguous registered Parquet dataset {dataset_name} for run {run_id}"
        )
    row = dict(rows[0])
    path = (root / row["relative_path"]).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("Registered Parquet path escapes the private workspace") from exc
    if not path.exists():
        raise FileNotFoundError(path)
    if row.get("sha256") and sha256_file(path) != row["sha256"]:
        raise ValueError(f"Registered Parquet hash mismatch: {dataset_name}")
    return path


def _load_shared_bottlenecks(
    root: Path,
    conn,
    *,
    tenant_key: str,
    compound_run_id: str,
) -> list[dict[str, Any]]:
    path = _registered_parquet_path(
        root,
        conn,
        dataset_name="compound_shared_flood_route_edges",
        run_id=compound_run_id,
    )
    if path is None:
        return []
    frame = pd.read_parquet(path)
    if "tenant_key" in frame.columns:
        frame = frame[frame["tenant_key"] == tenant_key].copy()
    keep = [
        x
        for x in [
            "physical_edge_key",
            "osm_way_id",
            "road_class",
            "bridge",
            "ferry",
            "length_m",
            "max_jrc_depth_m",
            "distinct_asset_count",
            "distinct_dependency_count",
        ]
        if x in frame.columns
    ]
    return frame[keep].to_dict(orient="records") if keep else []


def _load_logistics_dependencies(
    conn,
    *,
    tenant_key: str,
    route_run_id: str,
    asset_location_ids: list[str] | None,
) -> list[dict[str, Any]]:
    params: list[Any] = [tenant_key, route_run_id]
    where = ""
    if asset_location_ids:
        placeholders = ",".join("?" for _ in asset_location_ids)
        where = f" AND ard.asset_location_id IN ({placeholders})"
        params.extend(asset_location_ids)
    rows = conn.execute(
        f"""
        SELECT
            lra.route_analysis_id,
            ard.asset_location_id,
            al.external_system,
            al.external_id,
            ard.relationship,
            ard.shipment_share,
            re.endpoint_type,
            re.endpoint_name,
            lra.scenario_id,
            lra.baseline_length_m,
            lra.hazard_exposed_length_m,
            lra.hazard_exposed_share,
            lra.hazard_avoiding_length_m,
            lra.hazard_detour_ratio,
            lra.isolation_flag,
            lra.edge_disjoint_route_count,
            lra.edge_disjoint_route_count_after_hazard,
            lra.route_redundancy_loss,
            lra.quality_flag
        FROM logistics_route_analysis lra
        JOIN asset_route_dependency ard
          ON ard.asset_route_dependency_id=lra.asset_route_dependency_id
        JOIN asset_location al ON al.asset_location_id=ard.asset_location_id
        JOIN route_endpoint re ON re.route_endpoint_id=ard.route_endpoint_id
        WHERE lra.tenant_key=? AND lra.run_id=? {where}
        ORDER BY al.external_system, al.external_id, re.endpoint_type, re.endpoint_name
        """,
        tuple(params),
    ).fetchall()
    return [dict(row) for row in rows]


def _portfolio_rows(
    conn,
    *,
    tenant_key: str,
    portfolio_id: str,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT * FROM portfolio_exposure
        WHERE tenant_key=? AND portfolio_id=?
        ORDER BY exposure_type, exposure_id
        """,
        (tenant_key, portfolio_id),
    ).fetchall()
    if not rows:
        raise ValueError("No portfolio exposure rows match the requested tenant and portfolio")
    return [dict(row) for row in rows]


def _hazard_depth_map(
    conn,
    *,
    tenant_key: str,
    asset_location_ids: list[str],
    run_ids: list[str],
    indicator_id: str,
) -> dict[str, float | None]:
    if not asset_location_ids:
        return {}
    run_placeholders = ",".join("?" for _ in run_ids)
    asset_placeholders = ",".join("?" for _ in asset_location_ids)
    rows = conn.execute(
        f"""
        SELECT asset_location_id, value_numeric, value_text, null_reason, run_id
        FROM asset_indicator
        WHERE tenant_key=?
          AND indicator_id=?
          AND run_id IN ({run_placeholders})
          AND asset_location_id IN ({asset_placeholders})
        ORDER BY asset_location_id
        """,
        (tenant_key, indicator_id, *run_ids, *asset_location_ids),
    ).fetchall()
    out: dict[str, float | None] = {}
    for row in rows:
        key = row["asset_location_id"]
        if key in out:
            raise ValueError(
                f"Selected indicator runs contain multiple {indicator_id} rows for asset {key}"
            )
        if row["value_numeric"] is not None:
            out[key] = float(row["value_numeric"])
        else:
            out[key] = None
    return out


def _build_portfolio_report(
    conn,
    *,
    tenant_key: str,
    portfolio_id: str,
    indicator_run_ids: list[str],
    flood_indicator_id: str,
) -> tuple[dict[str, Any], list[str], dict[str, Any]]:
    rows = _portfolio_rows(conn, tenant_key=tenant_key, portfolio_id=portfolio_id)
    asset_ids = sorted(
        {str(x["asset_location_id"]) for x in rows if x.get("asset_location_id")}
    )
    depth_map = _hazard_depth_map(
        conn,
        tenant_key=tenant_key,
        asset_location_ids=asset_ids,
        run_ids=indicator_run_ids,
        indicator_id=flood_indicator_id,
    )

    metrics: list[dict[str, Any]] = []
    for exposure_type in _FINANCIAL_EXPOSURE_TYPES:
        subset = [x for x in rows if x["exposure_type"] == exposure_type]
        if not subset:
            continue
        currencies = {str(x["currency"]) for x in subset if x.get("currency")}
        if len(currencies) > 1:
            raise ValueError(
                f"{exposure_type} has multiple currencies; explicit FX conversion/vintage is required"
            )
        currency = next(iter(currencies), None)
        frame = pd.DataFrame(
            [
                {
                    "exposure_id": x["exposure_id"],
                    "amount": x["amount"],
                    "depth": depth_map.get(str(x["asset_location_id"]))
                    if x.get("asset_location_id")
                    else None,
                }
                for x in subset
            ]
        )
        result = exposure_in_footprint(frame, "amount", "depth", id_col="exposure_id")
        prefix = exposure_type.lower()
        vintage_dates = sorted(
            {str(x["valuation_date"]) for x in subset if x.get("valuation_date")}
        )
        vintage = (
            f"{vintage_dates[0]}..{vintage_dates[-1]}"
            if len(vintage_dates) > 1
            else (vintage_dates[0] if vintage_dates else None)
        )
        metrics.extend(
            [
                {
                    "metric_id": f"{prefix}_valid_total_for_{flood_indicator_id}",
                    "value": result["valid_exposure_total"],
                    "unit": currency,
                    "classification": "PORTFOLIO_EXPOSURE_ARITHMETIC",
                    "source_vintage": vintage,
                    "quality_flag": "OK" if result["n_valid"] else "NO_VALID_HAZARD_LINKS",
                },
                {
                    "metric_id": f"{prefix}_in_{flood_indicator_id}_footprint",
                    "value": result["exposure_in_footprint"],
                    "unit": currency,
                    "classification": "PORTFOLIO_EXPOSURE_ARITHMETIC",
                    "source_vintage": vintage,
                    "quality_flag": "OK" if result["n_valid"] else "NO_VALID_HAZARD_LINKS",
                },
                {
                    "metric_id": f"{prefix}_share_in_{flood_indicator_id}_footprint",
                    "value": result["exposure_share_in_footprint"],
                    "unit": "share",
                    "classification": "PORTFOLIO_CONCENTRATION",
                    "source_vintage": vintage,
                    "quality_flag": "OK" if result["n_valid"] else "NO_VALID_HAZARD_LINKS",
                    "denominator_count": result["n_valid"],
                },
            ]
        )

    linked = sum(1 for x in rows if x.get("asset_location_id"))
    missing_amount = sum(
        1
        for x in rows
        if x["exposure_type"] == "EAD" and x.get("amount") is None
    )
    resolved_assets = 0
    if asset_ids:
        placeholders = ",".join("?" for _ in asset_ids)
        resolved_assets = conn.execute(
            f"""
            SELECT count(*) AS n
            FROM asset_location
            WHERE tenant_key=?
              AND asset_location_id IN ({placeholders})
              AND site_identity_grade='EXACT_SITE'
              AND coordinate_status='RESOLVED'
            """,
            (tenant_key, *asset_ids),
        ).fetchone()["n"]

    missing_questions = []
    if linked < len(rows):
        missing_questions.append(
            "Link more portfolio exposure rows to governed asset locations."
        )
    if resolved_assets < len(asset_ids):
        missing_questions.append(
            "Improve linked-asset geocoding before relying on fine-resolution hazard metrics."
        )
    if missing_amount:
        missing_questions.append("Resolve missing EAD/outstanding exposure values.")
    missing_questions.extend(
        [
            "Add collateral market value, valuation date and LTV where collateral loss analysis is required.",
            "Add borrower revenue/cash-flow and sector-specific operating data before estimating credit-loss transmission.",
            "Add insurance coverage/sum insured before evaluating protection gaps.",
            "Add logistics endpoints and alternative routes before estimating common-bottleneck operational concentration.",
        ]
    )
    report = portfolio_intelligence_report(
        portfolio_id,
        metrics,
        missing_data_questions=missing_questions,
    )
    readiness = {
        "portfolio_exposure_row_count": len(rows),
        "portfolio_linked_asset_count": len(asset_ids),
        "portfolio_rows_with_asset_link": linked,
        "portfolio_valuation_dates": sorted(
            {str(x["valuation_date"]) for x in rows if x.get("valuation_date")}
        ),
        "portfolio_hazard_indicator": flood_indicator_id,
    }
    return report, asset_ids, readiness


def build_private_decision_workspace(
    root: str | Path,
    *,
    scope_type: str,
    tenant_key: str,
    indicator_run_ids: list[str],
    asset_location_id: str | None = None,
    external_system: str | None = None,
    external_id: str | None = None,
    portfolio_id: str | None = None,
    compound_run_id: str | None = None,
    route_run_id: str | None = None,
    flood_indicator_id: str = "flood_rp100_depth_m",
) -> tuple[dict[str, Any], dict[str, Any]]:
    root = _require_private_root(root)
    scope = str(scope_type).upper().strip()
    if scope not in {"ASSET", "PORTFOLIO"}:
        raise ValueError("scope_type must be ASSET or PORTFOLIO")
    if not str(tenant_key).strip():
        raise ValueError("tenant_key must be non-empty")

    with connect_catalog(root) as conn:
        indicator_runs = _require_runs(conn, indicator_run_ids)
        run_ids = [x["run_id"] for x in indicator_runs]
        _require_indicator_runs_for_tenant(
            conn,
            tenant_key=tenant_key,
            run_ids=run_ids,
        )

        asset_report = None
        portfolio_report = None
        asset_ids: list[str] = []
        provenance: list[dict[str, Any]] = []
        readiness: dict[str, Any] = {
            "indicator_runs": [
                {
                    "run_id": x["run_id"],
                    "pipeline_name": x["pipeline_name"],
                    "pipeline_version": x["pipeline_version"],
                    "git_commit": x.get("git_commit"),
                    "parameters": x.get("parameters", {}),
                }
                for x in indicator_runs
            ]
        }
        missing_data: list[dict[str, Any] | str] = []

        if scope == "ASSET":
            asset = _resolve_asset(
                conn,
                tenant_key=tenant_key,
                asset_location_id=asset_location_id,
                external_system=external_system,
                external_id=external_id,
            )
            asset_ids = [asset["asset_location_id"]]
            evidence, provenance = _load_asset_evidence(
                conn,
                tenant_key=tenant_key,
                asset_location_id=asset["asset_location_id"],
                run_ids=run_ids,
            )
            asset_report = asset_intelligence_report(
                {
                    "external_id": asset["external_id"],
                    "asset_type": asset["asset_type"],
                    "sector": None,
                    "site_identity_grade": asset["site_identity_grade"],
                    "coordinate_status": asset["coordinate_status"],
                },
                evidence,
                missing_data_questions=[
                    "Add finished-floor and critical-equipment elevation.",
                    "Add workforce by shift and operating hours.",
                    "Add cooling and backup-power capacity.",
                    "Add facility water source and use.",
                ],
            )
            subject_id = f"{asset['external_system']}:{asset['external_id']}"
            readiness.update(
                {
                    "asset_location_id": asset["asset_location_id"],
                    "site_identity_grade": asset["site_identity_grade"],
                    "coordinate_status": asset["coordinate_status"],
                    "coordinate_precision_m": asset.get("coordinate_precision_m"),
                    "direct_evidence_row_count": len(evidence),
                }
            )
        else:
            if not portfolio_id:
                raise ValueError("portfolio_id is required for PORTFOLIO scope")
            portfolio_report, asset_ids, portfolio_readiness = _build_portfolio_report(
                conn,
                tenant_key=tenant_key,
                portfolio_id=portfolio_id,
                indicator_run_ids=run_ids,
                flood_indicator_id=flood_indicator_id,
            )
            subject_id = portfolio_id
            readiness.update(portfolio_readiness)

        compound_report = None
        if compound_run_id:
            compound_run = _require_successful_run(conn, compound_run_id)
            _require_compound_run_for_tenant(
                conn,
                tenant_key=tenant_key,
                run_id=compound_run_id,
            )
            params = compound_run.get("parameters", {})
            if params.get("tenant") not in (None, tenant_key):
                raise ValueError("Compound run tenant does not match requested tenant")
            metrics, manifest = _load_cross_asset_metrics(
                conn,
                tenant_key=tenant_key,
                compound_run_id=compound_run_id,
            )
            compound_asset = _load_compound_asset_evidence(
                conn,
                tenant_key=tenant_key,
                compound_run_id=compound_run_id,
                asset_location_ids=asset_ids or None,
            )
            shared = _load_shared_bottlenecks(
                root,
                conn,
                tenant_key=tenant_key,
                compound_run_id=compound_run_id,
            )
            year = int(params.get("year", 0) or 0)
            return_period = int(params.get("return_period", 0) or 0)
            if year <= 0 or return_period <= 0:
                raise ValueError(
                    "Compound run parameters must contain positive year and return_period"
                )
            compound_report = compound_intelligence_report(
                tenant_key,
                year,
                return_period,
                compound_asset,
                metrics,
                shared,
                manifest,
            )
            readiness["compound_run"] = {
                "run_id": compound_run_id,
                "pipeline_name": compound_run["pipeline_name"],
                "pipeline_version": compound_run["pipeline_version"],
                "git_commit": compound_run.get("git_commit"),
                "parameters": params,
            }

        logistics = []
        if route_run_id:
            route_run = _require_successful_run(conn, route_run_id)
            _require_route_run_for_tenant(
                conn,
                tenant_key=tenant_key,
                run_id=route_run_id,
            )
            route_params = route_run.get("parameters", {})
            if route_params.get("tenant") not in (None, tenant_key):
                raise ValueError("Route run tenant does not match requested tenant")
            logistics = _load_logistics_dependencies(
                conn,
                tenant_key=tenant_key,
                route_run_id=route_run_id,
                asset_location_ids=asset_ids or None,
            )
            readiness["route_run"] = {
                "run_id": route_run_id,
                "pipeline_name": route_run["pipeline_name"],
                "pipeline_version": route_run["pipeline_version"],
                "git_commit": route_run.get("git_commit"),
                "parameters": route_params,
            }

    report = decision_workspace_report(
        scope_type=scope,
        tenant_scope=tenant_key,
        subject_id=subject_id,
        asset_report=asset_report,
        compound_report=compound_report,
        portfolio_report=portfolio_report,
        executive_summary=[],
        data_readiness=readiness,
        logistics_dependencies=logistics,
        evidence_provenance=provenance,
        missing_data=missing_data,
    )
    selection_manifest = {
        "scope_type": scope,
        "tenant_key": tenant_key,
        "subject_id": subject_id,
        "indicator_run_ids": run_ids,
        "compound_run_id": compound_run_id,
        "route_run_id": route_run_id,
        "flood_indicator_id": flood_indicator_id,
    }
    return report, selection_manifest


def write_private_decision_workspace(
    root: str | Path,
    report: dict[str, Any],
    *,
    selection_manifest: dict[str, Any],
    document_title: str = "Decision & Portfolio Report",
) -> dict[str, str]:
    root = _require_private_root(root)
    scope = report["scope"]
    out_dir = (
        root
        / "outputs"
        / "reports"
        / _safe_part(scope["tenant_scope"])
        / _safe_part(scope["scope_type"].lower())
        / _safe_part(scope["subject_id"])
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    stem = f"decision-workspace-{timestamp}"
    json_path = out_dir / f"{stem}.json"
    html_path = out_dir / f"{stem}.html"
    manifest_path = out_dir / f"{stem}.manifest.json"

    payload = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    json_path.write_text(payload, encoding="utf-8")
    html_path.write_text(
        render_decision_workspace_html(
            report,
            document_title=document_title,
            synthetic=False,
        ),
        encoding="utf-8",
    )
    manifest = {
        "report_type": report["report_type"],
        "schema_version": report["schema_version"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "selection": selection_manifest,
        "json_sha256": sha256_file(json_path),
        "html_sha256": sha256_file(html_path),
        "output_policy": "PRIVATE_WORKSPACE_ONLY",
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "json": json_path.relative_to(root).as_posix(),
        "html": html_path.relative_to(root).as_posix(),
        "manifest": manifest_path.relative_to(root).as_posix(),
    }


def build_and_write_private_decision_workspace(
    root: str | Path,
    **kwargs: Any,
) -> dict[str, Any]:
    report, selection = build_private_decision_workspace(root, **kwargs)
    outputs = write_private_decision_workspace(
        root,
        report,
        selection_manifest=selection,
    )
    return {
        "scope": report["scope"],
        "selection": selection,
        "outputs": outputs,
        "guardrails": [
            "Only explicitly named successful processing runs were used.",
            "Outputs were written inside the initialized private workspace.",
            "No composite score, PD, LGD, expected loss, damage or downtime was inferred.",
            "Portfolio financial aggregation blocks mixed currencies unless an explicit FX conversion is supplied upstream.",
        ],
    }
