from __future__ import annotations

import calendar
import json
import uuid
from pathlib import Path

import pandas as pd

from .local_store import (
    connect_catalog,
    parquet_partition_dir,
    register_parquet_dataset,
    sha256_file,
    utc_now,
)

HEAT_DROUGHT_METHOD="HEAT_DROUGHT_MONTHLY_JOIN_0.1"
FLOOD_ROUTE_METHOD="RP_SITE_ROUTE_EVIDENCE_0.1"
SHARED_BOTTLENECK_METHOD="SHARED_FLOOD_EXPOSED_EDGE_0.1"
CROSS_ASSET_METHOD="CROSS_ASSET_TRANSPARENT_COUNTS_0.1"


def _partition_matches(spec:dict,filters:dict|None)->bool:
    for key,value in (filters or {}).items():
        if key not in spec or str(spec[key])!=str(value):
            return False
    return True


def latest_parquet(
    root:str|Path,
    dataset_name:str,
    *,
    partition_filters:dict|None=None,
    run_id:str|None=None,
)->tuple[dict,Path]:
    root=Path(root).resolve()
    sql="""
        SELECT * FROM parquet_dataset
        WHERE dataset_name=?
    """
    params=[dataset_name]
    if run_id is not None:
        sql+=" AND run_id=?"
        params.append(run_id)
    sql+=" ORDER BY created_at DESC"
    with connect_catalog(root) as conn:
        rows=conn.execute(sql,tuple(params)).fetchall()
    for row in rows:
        rec=dict(row)
        try:
            spec=json.loads(rec.get("partition_spec_json") or "{}")
        except Exception:
            continue
        if not _partition_matches(spec,partition_filters):
            continue
        path=root/rec["relative_path"]
        if not path.exists():
            continue
        if rec.get("sha256") and sha256_file(path)!=rec["sha256"]:
            continue
        rec["partition_spec"]=spec
        return rec,path
    raise FileNotFoundError(
        f"No verified Parquet for {dataset_name} matching {partition_filters or {}}"
    )


def _dataset_manifest(*records:dict)->dict:
    return {
        "inputs":[
            {
                "parquet_dataset_id":r["parquet_dataset_id"],
                "dataset_name":r["dataset_name"],
                "sha256":r.get("sha256"),
                "relative_path":r["relative_path"],
                "partition_spec":r.get("partition_spec")
                or json.loads(r.get("partition_spec_json") or "{}"),
                "run_id":r.get("run_id"),
            }
            for r in records
        ]
    }


def heat_drought_monthly(
    daily_max:pd.DataFrame,
    spi_monthly:pd.DataFrame,
    *,
    year:int,
)->pd.DataFrame:
    required_heat={
        "asset_location_id","tenant_key","external_id","date","temp_c",
        "source_artifact_id",
    }
    required_spi={
        "asset_location_id","tenant_key","external_id","indicator_id",
        "period","value","quality_flag",
    }
    if not required_heat.issubset(daily_max.columns):
        raise ValueError(f"Daily heat missing {sorted(required_heat-set(daily_max.columns))}")
    if not required_spi.issubset(spi_monthly.columns):
        raise ValueError(f"SPI monthly missing {sorted(required_spi-set(spi_monthly.columns))}")

    heat=daily_max.copy()
    heat["date"]=pd.to_datetime(heat["date"])
    heat=heat[heat["date"].dt.year==int(year)].copy()
    heat["period"]=heat["date"].dt.to_period("M").astype(str)

    rows=[]
    for (asset_id,period),g in heat.groupby(["asset_location_id","period"]):
        p=pd.Period(period,freq="M")
        expected=calendar.monthrange(p.year,p.month)[1]
        temp=pd.to_numeric(g["temp_c"],errors="coerce")
        valid_temp=temp.notna()
        valid_days=g.loc[valid_temp,"date"].dt.date.nunique()
        sources=sorted(set(g["source_artifact_id"].dropna().astype(str)))
        if len(sources)!=1:
            raise ValueError(
                f"Heat month {asset_id}/{period} must have exactly one source artifact"
            )
        first=g.iloc[0]
        monthly_max=temp.loc[valid_temp].max() if bool(valid_temp.any()) else None
        rows.append({
            "tenant_key":first["tenant_key"],
            "asset_location_id":asset_id,
            "external_id":first["external_id"],
            "period":period,
            "heat_day_count":int(valid_days),
            "expected_day_count":int(expected),
            "days_tmax_gt_35c":(
                None
                if valid_days == 0
                else int(g.loc[temp.gt(35.0),"date"].dt.date.nunique())
            ),
            "days_tmax_gt_38c":(
                None
                if valid_days == 0
                else int(g.loc[temp.gt(38.0),"date"].dt.date.nunique())
            ),
            "monthly_max_tmax_c":(
                None if monthly_max is None or pd.isna(monthly_max)
                else float(monthly_max)
            ),
            "heat_source_artifact_id":sources[0],
            "heat_quality_flag":"OK" if valid_days==expected else "INCOMPLETE_HEAT_MONTH",
        })
    heat_monthly=pd.DataFrame(rows)

    spi=spi_monthly[
        spi_monthly["indicator_id"].isin(["spi3","spi12"])
    ].copy()
    spi=spi[spi["period"].astype(str).str.startswith(f"{int(year):04d}-")]
    if spi.duplicated(["asset_location_id","period","indicator_id"]).any():
        raise ValueError("SPI monthly contains duplicate asset/period/indicator rows")

    value_pivot=spi.pivot(
        index=["tenant_key","asset_location_id","external_id","period"],
        columns="indicator_id",values="value"
    ).reset_index()
    for scale in ("spi3","spi12"):
        if scale not in value_pivot.columns:
            value_pivot[scale]=pd.NA
    quality_pivot=spi.pivot(
        index=["tenant_key","asset_location_id","external_id","period"],
        columns="indicator_id",values="quality_flag"
    ).reset_index().rename(columns={
        "spi3":"spi3_quality_flag","spi12":"spi12_quality_flag"
    })
    for scale in ("spi3","spi12"):
        q=f"{scale}_quality_flag"
        if q not in quality_pivot.columns:
            quality_pivot[q]="MISSING_SPI_MONTH"
    joined=value_pivot.merge(
        quality_pivot,
        on=["tenant_key","asset_location_id","external_id","period"],
        how="outer",
    )
    out=heat_monthly.merge(
        joined,
        on=["tenant_key","asset_location_id","external_id","period"],
        how="left",
    )

    for scale in ("spi3","spi12"):
        q=f"{scale}_quality_flag"
        out[q]=out[q].fillna("MISSING_SPI_MONTH")
        out[f"{scale}_le_minus1"]=(
            out[scale].notna()
            & out[q].eq("OK")
            & out[scale].astype(float).le(-1.0)
        )
        out[f"heat_{scale}_cooccurrence"]=(
            out["heat_quality_flag"].eq("OK")
            & out["days_tmax_gt_35c"].gt(0)
            & out[f"{scale}_le_minus1"]
        )
        out[f"days_tmax_gt_35c_during_{scale}_le_minus1_month"]=out[
            "days_tmax_gt_35c"
        ].where(out[f"{scale}_le_minus1"],0)

    out["quality_flag"]=out.apply(
        lambda r:"OK"
        if (
            r["heat_quality_flag"]=="OK"
            and r["spi3_quality_flag"]=="OK"
            and r["spi12_quality_flag"]=="OK"
        )
        else "INCOMPLETE_COMPOUND_MONTH",
        axis=1,
    )
    return out.sort_values(["asset_location_id","period"]).reset_index(drop=True)


def heat_drought_annual(monthly:pd.DataFrame,*,year:int)->pd.DataFrame:
    rows=[]
    for asset_id,g in monthly.groupby("asset_location_id"):
        first=g.iloc[0]
        for scale in ("spi3","spi12"):
            valid=(
                g["heat_quality_flag"].eq("OK")
                & g[f"{scale}_quality_flag"].eq("OK")
            )
            quality="OK" if int(valid.sum())==12 else "INCOMPLETE_YEAR_INPUT"
            rows.append({
                "tenant_key":first["tenant_key"],
                "asset_location_id":asset_id,
                "external_id":first["external_id"],
                "indicator_id":f"compound_heat_drought_{scale}_cooccurrence_month_count",
                "value":None if quality!="OK" else float(
                    g.loc[valid,f"heat_{scale}_cooccurrence"].sum()
                ),
                "unit":"months/year","quality_flag":quality,
                "year":int(year),
            })
            rows.append({
                "tenant_key":first["tenant_key"],
                "asset_location_id":asset_id,
                "external_id":first["external_id"],
                "indicator_id":f"compound_heat_days_gt35_during_{scale}_le_minus1_months",
                "value":None if quality!="OK" else float(
                    g.loc[valid,f"days_tmax_gt_35c_during_{scale}_le_minus1_month"].sum()
                ),
                "unit":"days/year","quality_flag":quality,
                "year":int(year),
            })
    return pd.DataFrame(rows)


def latest_site_flood_depths(
    root:str|Path,
    *,
    return_period:int=100,
    tenant_key:str|None=None,
)->pd.DataFrame:
    indicator_id=f"flood_rp{int(return_period)}_depth_m"
    sql="""
        SELECT a.tenant_key,a.asset_location_id,a.external_system,a.external_id,
               ai.asset_indicator_id,ai.value_numeric AS site_depth_m,
               ai.quality_flag,ai.null_reason,ai.calculated_at
        FROM asset_location a
        LEFT JOIN asset_indicator ai
          ON ai.asset_indicator_id=(
              SELECT x.asset_indicator_id
              FROM asset_indicator x
              WHERE x.asset_location_id=a.asset_location_id
                AND x.indicator_id=?
              ORDER BY x.calculated_at DESC,x.asset_indicator_id DESC
              LIMIT 1
          )
        WHERE a.coordinate_status='RESOLVED'
          AND (a.valid_to IS NULL OR a.valid_to > datetime('now'))
    """
    params=[indicator_id]
    if tenant_key is not None:
        sql+=" AND a.tenant_key=?"
        params.append(tenant_key)
    with connect_catalog(root) as conn:
        rows=[dict(x) for x in conn.execute(sql,tuple(params)).fetchall()]
    return pd.DataFrame(rows)


def flood_route_asset_state(
    site_depths:pd.DataFrame,
    route_summary:pd.DataFrame,
    *,
    return_period:int=100,
)->pd.DataFrame:
    route=route_summary.copy()
    required={
        "tenant_key","external_system","external_id","quality_flag",
        "hazard_exposed_length_m","hazard_exposed_share",
    }
    if not required.issubset(route.columns):
        raise ValueError(f"Route summary missing {sorted(required-set(route.columns))}")

    route_rows=[]
    for keys,g in route.groupby(["tenant_key","external_system","external_id"],dropna=False):
        tenant,system,eid=keys
        complete=g["quality_flag"].eq("OK")
        complete_count=int(complete.sum())
        exposed_complete=int(
            (
                complete
                & pd.to_numeric(g["hazard_exposed_length_m"],errors="coerce").gt(0)
            ).sum()
        )
        max_share=(
            pd.to_numeric(g.loc[complete,"hazard_exposed_share"],errors="coerce").max()
            if complete_count else None
        )
        route_rows.append({
            "tenant_key":tenant,"external_system":system,"external_id":eid,
            "route_dependency_count":int(len(g)),
            "complete_route_hazard_count":complete_count,
            "exposed_complete_route_count":exposed_complete,
            "max_route_exposed_share":(
                None if max_share is None or pd.isna(max_share) else float(max_share)
            ),
            "all_route_hazard_coverage_complete":bool(complete_count==len(g)),
        })
    route_asset=pd.DataFrame(route_rows)

    site=site_depths.copy()
    out=site.merge(
        route_asset,
        on=["tenant_key","external_system","external_id"],
        how="outer",
    )
    for col in (
        "route_dependency_count","complete_route_hazard_count",
        "exposed_complete_route_count"
    ):
        out[col]=out[col].fillna(0).astype(int)
    out["all_route_hazard_coverage_complete"]=out[
        "all_route_hazard_coverage_complete"
    ].fillna(False)

    states=[]
    for row in out.to_dict(orient="records"):
        depth=row.get("site_depth_m")
        if depth is None or pd.isna(depth):
            states.append("SITE_HAZARD_UNAVAILABLE")
            continue
        if int(row["route_dependency_count"])==0:
            states.append("NO_ROUTE_DEPENDENCY")
            continue
        if not bool(row["all_route_hazard_coverage_complete"]):
            states.append("ROUTE_HAZARD_COVERAGE_INCOMPLETE")
            continue
        site_exposed=float(depth)>0
        route_exposed=int(row["exposed_complete_route_count"])>0
        if site_exposed and route_exposed:
            states.append("SITE_AND_ROUTE_EXPOSED")
        elif site_exposed:
            states.append("SITE_ONLY_EXPOSED")
        elif route_exposed:
            states.append("ROUTE_ONLY_EXPOSED")
        else:
            states.append("NEITHER_POINT_NOR_ROUTE_EXPOSED")
    out["evidence_state"]=states
    out["return_period"]=int(return_period)
    return out


def shared_flood_exposed_edges(edge_exposure:pd.DataFrame)->pd.DataFrame:
    required={
        "tenant_key","external_system","external_id","asset_route_dependency_id",
        "physical_edge_key","osm_way_id","road_class","bridge","ferry",
        "length_m","hazard_exposed","jrc_max_valid_depth_m",
    }
    if not required.issubset(edge_exposure.columns):
        raise ValueError(f"Route-edge exposure missing {sorted(required-set(edge_exposure.columns))}")
    x=edge_exposure[edge_exposure["hazard_exposed"]==True].copy()
    if x.empty:
        return pd.DataFrame(columns=[
            "tenant_key","physical_edge_key","osm_way_id","road_class","bridge","ferry",
            "length_m","max_jrc_depth_m","distinct_asset_count",
            "distinct_dependency_count","asset_keys",
        ])
    x["asset_key"]=x["external_system"].astype(str)+":"+x["external_id"].astype(str)
    rows=[]
    for (tenant,edge),g in x.groupby(["tenant_key","physical_edge_key"]):
        assets=sorted(set(g["asset_key"]))
        dependencies=set(g["asset_route_dependency_id"].astype(str))
        if len(assets)<=1:
            continue
        first=g.iloc[0]
        rows.append({
            "tenant_key":tenant,
            "physical_edge_key":edge,
            "osm_way_id":first["osm_way_id"],
            "road_class":first["road_class"],
            "bridge":bool(first["bridge"]),
            "ferry":bool(first["ferry"]),
            "length_m":float(g["length_m"].max()),
            "max_jrc_depth_m":float(
                pd.to_numeric(g["jrc_max_valid_depth_m"],errors="coerce").max()
            ),
            "distinct_asset_count":len(assets),
            "distinct_dependency_count":len(dependencies),
            "asset_keys":";".join(assets),
        })
    return pd.DataFrame(rows).sort_values(
        ["distinct_asset_count","distinct_dependency_count","length_m"],
        ascending=[False,False,False],
    ).reset_index(drop=True) if rows else pd.DataFrame(columns=[
        "tenant_key","physical_edge_key","osm_way_id","road_class","bridge","ferry",
        "length_m","max_jrc_depth_m","distinct_asset_count",
        "distinct_dependency_count","asset_keys",
    ])


def cross_asset_summary(
    heat_annual:pd.DataFrame,
    flood_route:pd.DataFrame,
    shared_edges:pd.DataFrame,
    *,
    year:int,
    shared_edge_evidence_available:bool,
    return_period:int=100,
)->pd.DataFrame:
    rows=[]
    if not heat_annual.empty:
        for scale in ("spi3","spi12"):
            iid=f"compound_heat_drought_{scale}_cooccurrence_month_count"
            g=heat_annual[heat_annual["indicator_id"]==iid]
            valid=g[g["quality_flag"]=="OK"]
            rows.extend([
                {
                    "analysis_type":"HEAT_DROUGHT",
                    "metric_id":f"assets_with_heat_{scale}_cooccurrence_count",
                    "value":float((valid["value"]>0).sum()),
                    "unit":"assets",
                    "denominator":int(len(valid)),
                    "quality_flag":"OK" if len(valid)>0 else "NO_VALID_ASSETS",
                    "period_start":f"{year}-01-01","period_end":f"{year}-12-31",
                },
                {
                    "analysis_type":"HEAT_DROUGHT",
                    "metric_id":f"asset_share_with_heat_{scale}_cooccurrence",
                    "value":None if len(valid)==0 else float((valid["value"]>0).mean()),
                    "unit":"share",
                    "denominator":int(len(valid)),
                    "quality_flag":"OK" if len(valid)>0 else "NO_VALID_ASSETS",
                    "period_start":f"{year}-01-01","period_end":f"{year}-12-31",
                },
            ])

    if not flood_route.empty:
        comparable=flood_route[
            flood_route["evidence_state"].isin([
                "SITE_AND_ROUTE_EXPOSED","SITE_ONLY_EXPOSED",
                "ROUTE_ONLY_EXPOSED","NEITHER_POINT_NOR_ROUTE_EXPOSED",
            ])
        ]
        both=int((comparable["evidence_state"]=="SITE_AND_ROUTE_EXPOSED").sum())
        rows.extend([
            {
                "analysis_type":"FLOOD_ROUTE",
                "metric_id":f"rp{return_period}_assets_site_and_route_exposed_count",
                "value":float(both),"unit":"assets",
                "denominator":int(len(comparable)),
                "quality_flag":"OK" if len(comparable)>0 else "NO_COMPARABLE_ASSETS",
                "period_start":None,"period_end":None,
            },
            {
                "analysis_type":"FLOOD_ROUTE",
                "metric_id":f"rp{return_period}_asset_share_site_and_route_exposed",
                "value":None if len(comparable)==0 else both/len(comparable),
                "unit":"share","denominator":int(len(comparable)),
                "quality_flag":"OK" if len(comparable)>0 else "NO_COMPARABLE_ASSETS",
                "period_start":None,"period_end":None,
            },
        ])

    shared_quality="OK" if shared_edge_evidence_available else "NO_ROUTE_EDGE_EVIDENCE"
    if not shared_edge_evidence_available:
        shared_edge_count=None
        affected_assets=None
        max_assets=None
    elif shared_edges.empty:
        shared_edge_count=0
        affected_assets=0
        max_assets=0
    else:
        shared_edge_count=int(len(shared_edges))
        asset_tokens=set()
        for value in shared_edges["asset_keys"].dropna().astype(str):
            asset_tokens.update(x for x in value.split(";") if x)
        affected_assets=len(asset_tokens)
        max_assets=int(shared_edges["distinct_asset_count"].max())
    rows.extend([
        {
            "analysis_type":"SHARED_BOTTLENECK",
            "metric_id":f"rp{return_period}_shared_flood_exposed_edge_count",
            "value":None if shared_edge_count is None else float(shared_edge_count),
            "unit":"edges",
            "denominator":None,"quality_flag":shared_quality,
            "period_start":None,"period_end":None,
        },
        {
            "analysis_type":"SHARED_BOTTLENECK",
            "metric_id":f"rp{return_period}_assets_using_shared_flood_exposed_edges_count",
            "value":None if affected_assets is None else float(affected_assets),
            "unit":"assets",
            "denominator":None,"quality_flag":shared_quality,
            "period_start":None,"period_end":None,
        },
        {
            "analysis_type":"SHARED_BOTTLENECK",
            "metric_id":f"rp{return_period}_max_assets_on_single_flood_exposed_edge",
            "value":None if max_assets is None else float(max_assets),
            "unit":"assets",
            "denominator":None,"quality_flag":shared_quality,
            "period_start":None,"period_end":None,
        },
    ])
    return pd.DataFrame(rows)


def _indicator_source_ids(
    root:str|Path,
    *,
    asset_location_id:str,
    run_id:str|None,
    indicator_ids:list[str],
)->set[str]:
    if not indicator_ids:
        return set()
    marks=",".join("?" for _ in indicator_ids)
    sql=f"""
        SELECT DISTINCT ais.source_artifact_id
        FROM asset_indicator ai
        JOIN asset_indicator_source ais
          ON ais.asset_indicator_id=ai.asset_indicator_id
        WHERE ai.asset_location_id=?
          AND ai.indicator_id IN ({marks})
    """
    params=[asset_location_id,*indicator_ids]
    if run_id is not None:
        sql+=" AND ai.run_id=?"
        params.append(run_id)
    with connect_catalog(root) as conn:
        return {
            str(x["source_artifact_id"])
            for x in conn.execute(sql,tuple(params)).fetchall()
        }


def insert_heat_drought_asset_indicators(
    root:str|Path,
    annual:pd.DataFrame,
    monthly:pd.DataFrame,
    *,
    heat_meta:dict,
    spi_meta:dict,
    year:int,
    run_id:str,
)->int:
    count=0
    with connect_catalog(root) as conn:
        for row in annual.to_dict(orient="records"):
            value=None if row["value"] is None or pd.isna(row["value"]) else float(row["value"])
            null_reason=None if value is not None else row["quality_flag"]
            cur=conn.execute(
                """
                INSERT INTO asset_indicator(
                    tenant_key,asset_location_id,indicator_id,value_numeric,value_text,
                    unit,value_class,measurement_basis,source_artifact_id,method_version,
                    period_start,period_end,quality_flag,null_reason,run_id,calculated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    row["tenant_key"],row["asset_location_id"],row["indicator_id"],
                    value,None,row["unit"],"CALCULATED",
                    "CALCULATED_FROM_REANALYSIS_AND_SATELLITE_GAUGE_PRECIPITATION",
                    None,HEAT_DROUGHT_METHOD,
                    f"{year}-01-01",f"{year}-12-31",
                    row["quality_flag"],null_reason,run_id,utc_now(),
                ),
            )
            heat_sources=set(
                monthly.loc[
                    monthly["asset_location_id"]==row["asset_location_id"],
                    "heat_source_artifact_id",
                ].dropna().astype(str)
            )
            drought_sources=_indicator_source_ids(
                root,
                asset_location_id=row["asset_location_id"],
                run_id=spi_meta.get("run_id"),
                indicator_ids=["spi3","spi12"],
            )
            for sid in sorted(heat_sources):
                conn.execute(
                    """
                    INSERT OR IGNORE INTO asset_indicator_source(
                        asset_indicator_id,source_artifact_id,source_role
                    ) VALUES(?,?,?)
                    """,(cur.lastrowid,sid,"COMPOUND_HEAT")
                )
            for sid in sorted(drought_sources):
                conn.execute(
                    """
                    INSERT OR IGNORE INTO asset_indicator_source(
                        asset_indicator_id,source_artifact_id,source_role
                    ) VALUES(?,?,?)
                    """,(cur.lastrowid,sid,"COMPOUND_DROUGHT")
                )
            count+=1
        conn.commit()
    return count


def _latest_indicator_lineage(
    root:str|Path,
    asset_indicator_id,
)->set[str]:
    if asset_indicator_id is None or pd.isna(asset_indicator_id):
        return set()
    with connect_catalog(root) as conn:
        rows=conn.execute(
            """
            SELECT source_artifact_id
            FROM asset_indicator_source
            WHERE asset_indicator_id=?
            """,(int(asset_indicator_id),)
        ).fetchall()
        if rows:
            return {str(x["source_artifact_id"]) for x in rows}
        row=conn.execute(
            "SELECT source_artifact_id FROM asset_indicator WHERE asset_indicator_id=?",
            (int(asset_indicator_id),)
        ).fetchone()
    return set() if not row or not row["source_artifact_id"] else {str(row["source_artifact_id"])}


def _route_run_source_roles(root:str|Path,route_run_id:str)->dict[str,set[str]]:
    out={"ROUTE_NETWORK_SOURCE":set(),"ROUTE_FLOOD_SOURCE":set()}
    with connect_catalog(root) as conn:
        rows=conn.execute(
            """
            SELECT DISTINCT lras.source_artifact_id,lras.source_role
            FROM logistics_route_analysis lra
            JOIN logistics_route_analysis_source lras
              ON lras.route_analysis_id=lra.route_analysis_id
            WHERE lra.run_id=?
            """,(route_run_id,)
        ).fetchall()
    for row in rows:
        role=(
            "ROUTE_NETWORK_SOURCE"
            if row["source_role"]=="OSM_PBF"
            else "ROUTE_FLOOD_SOURCE"
        )
        out[role].add(str(row["source_artifact_id"]))
    return out


def _route_run_source_ids(root:str|Path,route_run_id:str)->set[str]:
    roles=_route_run_source_roles(root,route_run_id)
    return set().union(*roles.values())


def run_indicator_source_ids(
    root:str|Path,
    *,
    run_id:str|None,
    indicator_ids:list[str],
    tenant_key:str|None=None,
)->set[str]:
    if run_id is None or not indicator_ids:
        return set()
    marks=",".join("?" for _ in indicator_ids)
    sql=f"""
        SELECT DISTINCT ais.source_artifact_id
        FROM asset_indicator ai
        JOIN asset_indicator_source ais
          ON ais.asset_indicator_id=ai.asset_indicator_id
        WHERE ai.run_id=?
          AND ai.indicator_id IN ({marks})
    """
    params=[run_id,*indicator_ids]
    if tenant_key is not None:
        sql+=" AND ai.tenant_key=?"
        params.append(tenant_key)
    with connect_catalog(root) as conn:
        rows=conn.execute(
            sql,tuple(params)
        ).fetchall()
    return {str(x["source_artifact_id"]) for x in rows}


def site_flood_source_ids(
    root:str|Path,
    site_depths:pd.DataFrame,
)->set[str]:
    out=set()
    if site_depths.empty or "asset_indicator_id" not in site_depths:
        return out
    for value in site_depths["asset_indicator_id"].dropna():
        out.update(_latest_indicator_lineage(root,value))
    return out


def insert_flood_route_asset_indicators(
    root:str|Path,
    frame:pd.DataFrame,
    *,
    route_meta:dict,
    return_period:int,
    run_id:str,
)->int:
    count=0
    route_sources=_route_run_source_ids(root,str(route_meta.get("run_id")))
    with connect_catalog(root) as conn:
        for row in frame.to_dict(orient="records"):
            asset_id=row.get("asset_location_id")
            if asset_id is None or pd.isna(asset_id):
                continue
            specs=[
                (
                    f"rp{return_period}_site_route_exposure_state",
                    None,row["evidence_state"],None,
                ),
                (
                    f"rp{return_period}_route_dependency_count",
                    float(row["route_dependency_count"]),None,"routes",
                ),
                (
                    f"rp{return_period}_exposed_complete_route_count",
                    float(row["exposed_complete_route_count"]),None,"routes",
                ),
                (
                    f"rp{return_period}_max_route_exposed_share",
                    row.get("max_route_exposed_share"),None,"share",
                ),
            ]
            for indicator_id,value_numeric,value_text,unit in specs:
                if value_numeric is not None and pd.isna(value_numeric):
                    value_numeric=None
                null_reason=None
                if value_numeric is None and value_text is None:
                    null_reason=(
                        "ROUTE_HAZARD_COVERAGE_INCOMPLETE"
                        if row["evidence_state"]=="ROUTE_HAZARD_COVERAGE_INCOMPLETE"
                        else "NO_ROUTE_VALUE"
                    )
                cur=conn.execute(
                    """
                    INSERT INTO asset_indicator(
                        tenant_key,asset_location_id,indicator_id,value_numeric,value_text,
                        unit,value_class,measurement_basis,source_artifact_id,method_version,
                        period_start,period_end,quality_flag,null_reason,run_id,calculated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        row["tenant_key"],asset_id,indicator_id,
                        value_numeric,value_text,unit,"CALCULATED",
                        "CALCULATED_FROM_MODELLED_SITE_AND_ROUTE_FLOOD_EVIDENCE",
                        None,FLOOD_ROUTE_METHOD,None,None,
                        row["evidence_state"],null_reason,run_id,utc_now(),
                    ),
                )
                site_sources=_latest_indicator_lineage(
                    root,row.get("asset_indicator_id")
                )
                for sid in sorted(site_sources):
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO asset_indicator_source(
                            asset_indicator_id,source_artifact_id,source_role
                        ) VALUES(?,?,?)
                        """,(cur.lastrowid,sid,"COMPOUND_SITE_FLOOD")
                    )
                for sid in sorted(route_sources):
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO asset_indicator_source(
                            asset_indicator_id,source_artifact_id,source_role
                        ) VALUES(?,?,?)
                        """,(cur.lastrowid,sid,"COMPOUND_ROUTE_FLOOD")
                    )
                count+=1
        conn.commit()
    return count


def _insert_cross_metric(
    root:str|Path,
    *,
    tenant_key:str,
    analysis_type:str,
    metric_id:str,
    value,
    unit:str|None,
    period_start:str|None,
    period_end:str|None,
    method_version:str,
    quality_flag:str,
    input_manifest:dict,
    run_id:str,
    source_roles:dict[str,set[str]],
    denominator:int|None=None,
)->str:
    metric_id_pk=str(uuid.uuid4())
    value_numeric=None if value is None or pd.isna(value) else float(value)
    null_reason=None if value_numeric is not None else quality_flag
    manifest=dict(input_manifest)
    denominator_value=(
        None if denominator is None or pd.isna(denominator)
        else int(denominator)
    )
    if denominator_value is not None:
        if denominator_value<0:
            raise ValueError("denominator cannot be negative")
        manifest["denominator"]=denominator_value
    with connect_catalog(root) as conn:
        conn.execute(
            """
            INSERT INTO cross_asset_metric(
                cross_asset_metric_id,tenant_key,analysis_type,scope_key,
                metric_id,value_numeric,value_text,unit,period_start,period_end,
                method_version,quality_flag,null_reason,input_manifest_json,
                run_id,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                metric_id_pk,tenant_key,analysis_type,"ALL_ASSETS",
                metric_id,value_numeric,None,unit,period_start,period_end,
                method_version,quality_flag,null_reason,
                json.dumps(manifest,sort_keys=True),
                run_id,utc_now(),
            ),
        )
        for role,source_ids in source_roles.items():
            for sid in sorted(source_ids):
                conn.execute(
                    """
                    INSERT OR IGNORE INTO cross_asset_metric_source(
                        cross_asset_metric_id,source_artifact_id,source_role
                    ) VALUES(?,?,?)
                    """,(metric_id_pk,sid,role)
                )
        conn.commit()
    return metric_id_pk


def insert_cross_asset_summary(
    root:str|Path,
    summary:pd.DataFrame,
    *,
    tenant_key:str,
    heat_meta:dict,
    spi_meta:dict,
    route_meta:dict,
    route_edge_meta:dict,
    site_depths:pd.DataFrame,
    year:int,
    return_period:int,
    run_id:str,
)->int:
    _,heat_path=latest_parquet(
        root,"era5_land_daily_temperature",
        partition_filters={"year":year,"statistic":"daily_maximum"},
        run_id=heat_meta.get("run_id"),
    )
    heat_frame=pd.read_parquet(
        heat_path,
        columns=["tenant_key","source_artifact_id"],
    )
    heat_sources=set(
        heat_frame.loc[
            heat_frame["tenant_key"]==tenant_key,
            "source_artifact_id",
        ].dropna().astype(str)
    )

    drought_sources=run_indicator_source_ids(
        root,run_id=spi_meta.get("run_id"),
        indicator_ids=["spi3","spi12"],tenant_key=tenant_key
    )
    if bool((summary["analysis_type"]=="HEAT_DROUGHT").any()):
        if not heat_sources:
            raise ValueError(
                f"Heat lineage unavailable for tenant {tenant_key}"
            )
        if not drought_sources:
            raise ValueError(
                f"Drought lineage unavailable for tenant {tenant_key}"
            )
    route_roles=_route_run_source_roles(
        root,str(route_meta.get("run_id"))
    )
    site_sources=site_flood_source_ids(root,site_depths)

    manifest=_dataset_manifest(heat_meta,spi_meta,route_meta,route_edge_meta)
    count=0
    for row in summary.to_dict(orient="records"):
        analysis=row["analysis_type"]
        if analysis=="HEAT_DROUGHT":
            roles={
                "HEAT_SOURCE":heat_sources,
                "DROUGHT_SOURCE":drought_sources,
            }
            method=HEAT_DROUGHT_METHOD
        elif analysis=="FLOOD_ROUTE":
            roles={
                "SITE_FLOOD_SOURCE":site_sources,
                **route_roles,
            }
            method=FLOOD_ROUTE_METHOD
        elif analysis=="SHARED_BOTTLENECK":
            roles=route_roles
            method=SHARED_BOTTLENECK_METHOD
        else:
            roles={}
            method=CROSS_ASSET_METHOD

        _insert_cross_metric(
            root,tenant_key=tenant_key,
            analysis_type=analysis,
            metric_id=row["metric_id"],
            value=row["value"],unit=row["unit"],
            period_start=row.get("period_start"),
            period_end=row.get("period_end"),
            method_version=method,
            quality_flag=row["quality_flag"],
            input_manifest=manifest,
            run_id=run_id,source_roles=roles,
            denominator=row.get("denominator"),
        )
        count+=1
    return count


def write_compound_parquets(
    root:str|Path,
    *,
    heat_monthly:pd.DataFrame,
    heat_annual:pd.DataFrame,
    flood_route:pd.DataFrame,
    shared_edges:pd.DataFrame,
    cross_summary:pd.DataFrame,
    year:int,
    return_period:int,
    run_id:str,
)->dict[str,Path]:
    root=Path(root).resolve()
    directory=parquet_partition_dir(
        root,layer="indicators",dataset="compound_cross_asset_intelligence",
        partitions={"year":int(year),"return_period":int(return_period)},
    )
    directory.mkdir(parents=True,exist_ok=True)
    outputs={}
    frames={
        "heat_drought_monthly":heat_monthly,
        "heat_drought_annual":heat_annual,
        "flood_route_asset_state":flood_route,
        "shared_flood_route_edges":shared_edges,
        "cross_asset_summary":cross_summary,
    }
    for name,frame in frames.items():
        path=directory/f"{name}-{run_id}.parquet"
        frame.to_parquet(path,index=False)
        register_parquet_dataset(
            root,dataset_name=f"compound_{name}",layer="indicators",
            parquet_path=path,
            partition_spec={"year":int(year),"return_period":int(return_period)},
            row_count=len(frame),run_id=run_id,
        )
        outputs[name]=path
    return outputs
