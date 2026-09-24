from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))

from clr.compound_local import (
    cross_asset_summary,
    flood_route_asset_state,
    heat_drought_annual,
    heat_drought_monthly,
    insert_cross_asset_summary,
    insert_flood_route_asset_indicators,
    insert_heat_drought_asset_indicators,
    latest_parquet,
    latest_site_flood_depths,
    shared_flood_exposed_edges,
    write_compound_parquets,
)
from clr.local_store import finish_processing_run,start_processing_run

parser=argparse.ArgumentParser(
    description="Build transparent compound-hazard and cross-asset intelligence."
)
parser.add_argument("--year",type=int,default=2025)
parser.add_argument("--return-period",type=int,default=100)
parser.add_argument(
    "--root",default=os.getenv("CLR_PRIVATE_DATA",str(ROOT/"private_data"))
)
parser.add_argument("--tenant",default="INTERNAL")
args=parser.parse_args()

if args.year<1950:
    raise SystemExit("--year must be >=1950")
if args.return_period<=0:
    raise SystemExit("--return-period must be positive")
if not args.tenant:
    raise SystemExit("--tenant must be non-empty")

root=Path(args.root).resolve()
try:
    git_commit=subprocess.run(
        ["git","rev-parse","HEAD"],cwd=ROOT,
        capture_output=True,text=True,check=True
    ).stdout.strip()
except Exception:
    git_commit=None

run_id=start_processing_run(
    root,pipeline_name="compound_cross_asset_intelligence",
    pipeline_version="0.1.0",git_commit=git_commit,
    profile_name="compound_cross_asset",
    parameters={
        "year":args.year,
        "return_period":args.return_period,
        "tenant":args.tenant,
        "heat_threshold_c":35.0,
        "drought_spi_threshold":-1.0,
        "scope":"single_tenant",
    },
)

try:
    heat_meta,heat_path=latest_parquet(
        root,"era5_land_daily_temperature",
        partition_filters={
            "year":args.year,"statistic":"daily_maximum"
        },
    )
    spi_meta,spi_path=latest_parquet(
        root,"chirps_spi_monthly",
        partition_filters={"year":args.year},
    )
    route_meta,route_path=latest_parquet(
        root,"osm_route_flood_summary",
        partition_filters={"return_period":args.return_period},
    )
    route_edge_meta,route_edge_path=latest_parquet(
        root,"osm_route_flood_edge_exposure",
        partition_filters={"return_period":args.return_period},
        run_id=route_meta["run_id"],
    )

    heat=pd.read_parquet(heat_path)
    spi=pd.read_parquet(spi_path)
    route_summary=pd.read_parquet(route_path)
    route_edges=pd.read_parquet(route_edge_path)

    heat=heat[heat["tenant_key"]==args.tenant].copy()
    spi=spi[spi["tenant_key"]==args.tenant].copy()
    route_summary=route_summary[
        route_summary["tenant_key"]==args.tenant
    ].copy()
    route_edges=route_edges[
        route_edges["tenant_key"]==args.tenant
    ].copy()

    if heat.empty:
        raise ValueError(f"No ERA5 daily-max rows for tenant {args.tenant}")
    if spi.empty:
        raise ValueError(f"No SPI monthly rows for tenant {args.tenant}")

    hd_monthly=heat_drought_monthly(
        heat,spi,year=args.year
    )
    hd_annual=heat_drought_annual(
        hd_monthly,year=args.year
    )

    site_depths=latest_site_flood_depths(
        root,return_period=args.return_period,
        tenant_key=args.tenant,
    )
    fr_state=flood_route_asset_state(
        site_depths,route_summary,
        return_period=args.return_period,
    )
    shared_edges=shared_flood_exposed_edges(route_edges)
    summary=cross_asset_summary(
        hd_annual,fr_state,shared_edges,
        year=args.year,return_period=args.return_period,
    )

    outputs=write_compound_parquets(
        root,
        heat_monthly=hd_monthly,
        heat_annual=hd_annual,
        flood_route=fr_state,
        shared_edges=shared_edges,
        cross_summary=summary,
        year=args.year,
        return_period=args.return_period,
        run_id=run_id,
    )

    asset_heat_rows=insert_heat_drought_asset_indicators(
        root,hd_annual,hd_monthly,
        heat_meta=heat_meta,spi_meta=spi_meta,
        year=args.year,run_id=run_id,
    )
    asset_flood_route_rows=insert_flood_route_asset_indicators(
        root,fr_state,route_meta=route_meta,
        return_period=args.return_period,run_id=run_id,
    )
    cross_rows=insert_cross_asset_summary(
        root,summary,tenant_key=args.tenant,
        heat_meta=heat_meta,spi_meta=spi_meta,
        route_meta=route_meta,route_edge_meta=route_edge_meta,
        site_depths=site_depths,
        year=args.year,return_period=args.return_period,
        run_id=run_id,
    )

    finish_processing_run(root,run_id,status="SUCCESS")
    print(json.dumps({
        "run_id":run_id,
        "status":"SUCCESS",
        "tenant":args.tenant,
        "year":args.year,
        "return_period":args.return_period,
        "heat_drought_month_rows":len(hd_monthly),
        "heat_drought_asset_indicator_rows":asset_heat_rows,
        "flood_route_asset_rows":len(fr_state),
        "flood_route_asset_indicator_rows":asset_flood_route_rows,
        "shared_flood_exposed_edges":len(shared_edges),
        "cross_asset_metric_rows":cross_rows,
        "outputs":{k:str(v) for k,v in outputs.items()},
        "guardrails":[
            "No composite risk score.",
            "Heat-drought is a same-month evidence join, not a loss estimate.",
            "Flood-exposed route is not a blocked route.",
            "Cross-asset shares use explicit valid-data denominators.",
            "Metrics are scoped to one tenant and do not mix customers."
        ],
    },indent=2))
except Exception as e:
    finish_processing_run(
        root,run_id,status="FAILED",
        error_summary=f"{type(e).__name__}: {e}"
    )
    raise
