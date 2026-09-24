from __future__ import annotations

from clr.decision_reports import decision_workspace_report
from clr.product_output import (
    asset_intelligence_report,
    compound_intelligence_report,
    portfolio_intelligence_report,
)


def synthetic_decision_workspace_report() -> dict:
    """Return a fully synthetic decision-workspace demonstration payload."""
    asset = asset_intelligence_report(
        {
            "external_id": "SYNTH_FACTORY_A",
            "asset_type": "FACTORY",
            "sector": "RMG",
            "site_identity_grade": "EXACT_SITE",
            "coordinate_status": "RESOLVED",
        },
        [
            {
                "indicator_id": "days_tmax_gt_35c",
                "label": "Days above 35°C",
                "value": 24,
                "unit": "days",
                "value_class": "CALCULATED",
                "measurement_basis": "CALCULATED_FROM_REANALYSIS",
                "source_id": "ERA5_LAND_DAILY",
                "source_vintage": "SYNTH_2025",
                "quality_flag": "OK",
                "period_start": "2025-01-01",
                "period_end": "2025-12-31",
                "method_version": "HEAT_0.1",
            },
            {
                "indicator_id": "flood_rp100_depth_m",
                "label": "RP100 modelled river-flood depth",
                "value": 0.6,
                "unit": "m",
                "value_class": "SOURCE",
                "measurement_basis": "HYDROLOGICAL_HYDRODYNAMIC_MODEL",
                "source_id": "JRC_CEMS_RP100",
                "source_vintage": "SYNTH_VINTAGE",
                "quality_flag": "OK",
                "method_version": "JRC_0.1",
            },
            {
                "indicator_id": "rx5day_mm",
                "label": "Maximum five-day rainfall",
                "value": 162,
                "unit": "mm",
                "value_class": "CALCULATED",
                "measurement_basis": "CALCULATED_FROM_BLENDED_RAINFALL",
                "source_id": "CHIRPS_V3",
                "source_vintage": "SYNTH_2025",
                "quality_flag": "OK",
                "period_start": "2025-01-01",
                "period_end": "2025-12-31",
                "method_version": "RAIN_0.1",
            },
            {
                "indicator_id": "relative_dsm_elevation_500m_m",
                "label": "DSM elevation relative to 500 m median",
                "value": -1.8,
                "unit": "m",
                "value_class": "CALCULATED",
                "measurement_basis": "CALCULATED_FROM_DSM",
                "source_id": "COPERNICUS_DEM_GLO30",
                "source_vintage": "SYNTH_VINTAGE",
                "quality_flag": "OK",
                "method_version": "DEM_0.1",
            },
            {
                "indicator_id": "population_5km",
                "label": "Modeled residential population within 5 km",
                "value": 86000,
                "unit": "people",
                "value_class": "SOURCE",
                "measurement_basis": "MODELED_RESIDENTIAL_POPULATION",
                "source_id": "WORLDPOP_GLOBAL2",
                "source_vintage": "SYNTH_2025",
                "quality_flag": "OK",
                "method_version": "WORLDPOP_0.1",
            },
            {
                "indicator_id": "surface_water_distance_occ90_m",
                "label": "Distance to ≥90% long-run surface water",
                "value": 420,
                "unit": "m",
                "value_class": "CALCULATED",
                "measurement_basis": "CALCULATED_FROM_LONG_RUN_WATER_OCCURRENCE",
                "source_id": "JRC_GSW_V1_5",
                "source_vintage": "SYNTH_VINTAGE",
                "quality_flag": "OK",
                "method_version": "GSW_0.1",
            },
            {
                "indicator_id": "observed_flood_site_detection",
                "label": "Observed flood detection at exact site",
                "value": None,
                "unit": None,
                "value_class": "SOURCE",
                "measurement_basis": "SATELLITE_OBSERVED_EVENT",
                "source_id": "COPERNICUS_GFM",
                "source_vintage": "SYNTH_EVENT",
                "quality_flag": "NO_VALID_EVENT_COVERAGE",
                "null_reason": "No valid synthetic event coverage for this demonstration period.",
                "method_version": "GFM_0.1",
            },
        ],
        findings=[
            {
                "level": "SECOND_ORDER_EXPOSURE",
                "finding_id": "WORKER_HEAT_EXPOSURE",
                "text": "1,500 workers × 24 extreme-heat days = 36,000 worker-heat exposure days.",
                "research_refs": ["R007", "R008", "R011"],
                "guardrail": "Exposure arithmetic only; it is not an estimate of lost workdays, productivity loss, or health outcomes.",
            },
            {
                "level": "THIRD_ORDER_QUESTION",
                "finding_id": "FLOOR_ELEVATION_QUESTION",
                "text": "The site is inside the modelled RP100 footprint, but equipment and finished-floor elevation are not supplied.",
                "research_refs": ["R001"],
                "guardrail": "Modelled point depth does not by itself establish floor inundation, damage, or downtime.",
            },
        ],
        missing_data_questions=[
            "Add finished-floor and critical-equipment elevation.",
            "Add workforce by shift and operating hours.",
            "Add cooling and backup-power capacity.",
            "Add facility water source and use.",
        ],
    )

    compound = compound_intelligence_report(
        "SYNTHETIC_PUBLIC",
        2025,
        100,
        asset_compound_evidence=[
            {
                "external_id": "SYNTH_FACTORY_A",
                "evidence_state": "SITE_AND_ROUTE_EXPOSED",
                "heat_spi3_cooccurrence_month_count": 2,
                "quality_flag": "OK",
                "guardrail": "Same-month co-occurrence and site-route exposure do not establish economic loss.",
            }
        ],
        cross_asset_metrics=[
            {
                "analysis_type": "HEAT_DROUGHT",
                "metric_id": "asset_share_with_heat_spi3_cooccurrence",
                "value": 0.5,
                "unit": "share",
                "denominator": 4,
                "quality_flag": "OK",
                "period_start": "2025-01-01",
                "period_end": "2025-12-31",
            },
            {
                "analysis_type": "SITE_ROUTE_FLOOD",
                "metric_id": "rp100_asset_share_site_and_route_exposed",
                "value": 0.5,
                "unit": "share",
                "denominator": 4,
                "quality_flag": "OK",
            },
            {
                "analysis_type": "SHARED_BOTTLENECK",
                "metric_id": "shared_flood_exposed_edge_count",
                "value": 2,
                "unit": "edges",
                "denominator": None,
                "quality_flag": "OK",
            },
        ],
        shared_bottlenecks=[
            {
                "physical_edge_key": "SYNTH_EDGE_01",
                "distinct_asset_count": 3,
                "distinct_dependency_count": 4,
                "max_jrc_depth_m": 0.8,
                "road_class": "primary",
            }
        ],
        input_manifest={
            "inputs": [
                {"dataset_name": "ERA5-Land synthetic fixture", "partition_spec": "year=2025"},
                {"dataset_name": "CHIRPS v3 synthetic fixture", "partition_spec": "year=2025"},
                {"dataset_name": "JRC RP100 synthetic fixture", "partition_spec": "rp=100"},
                {"dataset_name": "OSM synthetic route fixture", "partition_spec": "synthetic"},
            ]
        },
    )

    portfolio = portfolio_intelligence_report(
        "SYNTH_PORTFOLIO_01",
        [
            {
                "metric_id": "ead_share_in_rp100_footprint",
                "value": 0.25,
                "unit": "share",
                "denominator_count": 4,
                "classification": "BANK_CONCENTRATION",
                "source_vintage": "SYNTH_VINTAGE",
                "quality_flag": "OK",
            },
            {
                "metric_id": "ead_in_rp100_footprint",
                "value": 125000000,
                "unit": "BDT",
                "classification": "BANK_EXPOSURE_ARITHMETIC",
                "source_vintage": "SYNTH_VINTAGE",
                "quality_flag": "OK",
            },
        ],
        missing_data_questions=[
            "Add collateral market value and valuation date.",
            "Add insurance coverage and sum insured.",
        ],
    )

    return decision_workspace_report(
        scope_type="PORTFOLIO",
        tenant_scope="SYNTHETIC_PUBLIC",
        subject_id="SYNTH_PORTFOLIO_01",
        asset_report=asset,
        compound_report=compound,
        portfolio_report=portfolio,
        executive_summary=[
            {
                "statement_id": "S1",
                "text": "The synthetic factory has direct heat, modelled flood, rainfall, terrain, population, and surface-water context with source and vintage fields preserved.",
                "evidence_class": "DIRECT",
                "source_refs": ["ASSET_INTELLIGENCE"],
                "guardrail": "The evidence dimensions remain separate and are not combined into a score.",
            },
            {
                "statement_id": "S2",
                "text": "Synthetic same-month heat–drought co-occurrence and site-plus-route flood exposure are present.",
                "evidence_class": "COMPOUND",
                "source_refs": ["COMPOUND_CROSS_ASSET_INTELLIGENCE"],
                "guardrail": "Co-occurrence and route exposure do not establish loss, causality, or closure.",
            },
            {
                "statement_id": "S3",
                "text": "One synthetic flood-exposed road edge is shared by three distinct assets.",
                "evidence_class": "CROSS_ASSET",
                "source_refs": ["COMPOUND_CROSS_ASSET_INTELLIGENCE"],
                "guardrail": "Shared dependence is concentration evidence, not a disruption probability.",
            },
            {
                "statement_id": "S4",
                "text": "Synthetic portfolio exposure metrics are available, but collateral value, insurance terms, and operating resilience data remain incomplete.",
                "evidence_class": "MISSING_DATA",
                "source_refs": [],
                "guardrail": "No PD, LGD, expected loss, or insurance loss is inferred.",
            },
        ],
        data_readiness={
            "site_identity_grade": "EXACT_SITE",
            "coordinate_status": "RESOLVED",
            "direct_evidence_rows": 7,
            "compound_year": 2025,
            "flood_return_period": "RP100",
            "public_demo_status": "SYNTHETIC_ONLY",
        },
        operational_transmission=[
            {
                "level": "OPERATIONAL_QUESTION",
                "finding_id": "COOLING_BACKUP_POWER",
                "text": "Cooling capacity and backup power are not supplied, so heat exposure is not translated into production interruption.",
                "guardrail": "No downtime estimate is produced without operational evidence.",
            }
        ],
        logistics_dependencies=[
            {
                "dependency_id": "SYNTH_PORT_ROUTE",
                "evidence_state": "ROUTE_EXPOSED",
                "description": "A synthetic primary-road dependency intersects positive modelled RP100 depth.",
                "guardrail": "Route exposure does not establish road closure, impassability, or delivery delay.",
            }
        ],
        evidence_provenance=[
            {
                "source_module": "ASSET_INTELLIGENCE",
                "input_manifest": {
                    "inputs": [
                        {"dataset_name": "Synthetic public asset evidence"}
                    ]
                },
            }
        ],
        missing_data=[
            {
                "data_item": "Add exact route and port dependency by shipment type.",
                "why_it_matters": "It would separate generic route exposure from business-critical logistics dependence.",
                "decision_question": "Which route failures could interrupt inbound or outbound flows?",
                "source_module": "LOGISTICS",
            }
        ],
    )
