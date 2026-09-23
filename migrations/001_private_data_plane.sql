-- Private operational data plane for Bangladesh Climate & Location Risk Intelligence.
-- Schema only. No real asset/customer/source records belong in GitHub.

create extension if not exists postgis;

create schema if not exists clr_private;

revoke all on schema clr_private from public;
revoke all on schema clr_private from anon;
revoke all on schema clr_private from authenticated;
grant usage on schema clr_private to service_role;

create table if not exists clr_private.tenant (
    tenant_id uuid primary key default gen_random_uuid(),
    tenant_key text not null unique,
    tenant_type text not null check (tenant_type in ('INTERNAL','FACTORY','BANK','NBFI','INSURER','INVESTOR','OTHER')),
    status text not null default 'ACTIVE' check (status in ('ACTIVE','SUSPENDED','CLOSED')),
    created_at timestamptz not null default now()
);

create table if not exists clr_private.asset_location (
    asset_location_id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references clr_private.tenant(tenant_id),
    external_system text not null,
    external_id text not null,
    asset_type text not null,
    geom geometry(Point,4326) not null,
    coordinate_source text not null,
    coordinate_precision_m numeric,
    site_identity_grade text not null check (site_identity_grade in ('EXACT_SITE','PROBABLE_SITE','LOCALITY_ONLY','AMBIGUOUS','NO_MATCH','REJECTED_ADMIN_MISMATCH')),
    coordinate_status text not null check (coordinate_status in ('RESOLVED','PENDING','REJECTED')),
    valid_from timestamptz,
    valid_to timestamptz,
    created_at timestamptz not null default now(),
    unique (tenant_id, external_system, external_id, valid_from)
);

create index if not exists asset_location_geom_gix
    on clr_private.asset_location using gist (geom);

create table if not exists clr_private.source_artifact (
    source_artifact_id uuid primary key default gen_random_uuid(),
    source_id text not null,
    provider text not null,
    provider_version text,
    object_uri text not null,
    sha256 text not null check (sha256 ~ '^[0-9a-f]{64}$'),
    byte_size bigint check (byte_size is null or byte_size >= 0),
    media_type text,
    retrieved_at timestamptz not null,
    valid_time_start timestamptz,
    valid_time_end timestamptz,
    request_manifest_sha256 text check (request_manifest_sha256 is null or request_manifest_sha256 ~ '^[0-9a-f]{64}$'),
    retrieval_status text not null check (retrieval_status in ('COMPLETE','PARTIAL','FAILED','BLOCKED')),
    note text,
    unique (source_id, sha256)
);

create table if not exists clr_private.processing_run (
    run_id uuid primary key default gen_random_uuid(),
    pipeline_name text not null,
    pipeline_version text not null,
    git_commit text,
    profile_name text,
    started_at timestamptz not null default now(),
    finished_at timestamptz,
    status text not null check (status in ('RUNNING','SUCCESS','FAILED','PARTIAL')),
    parameters jsonb not null default '{}'::jsonb,
    error_summary text
);

create table if not exists clr_private.asset_indicator (
    asset_indicator_id bigint generated always as identity primary key,
    tenant_id uuid not null references clr_private.tenant(tenant_id),
    asset_location_id uuid not null references clr_private.asset_location(asset_location_id),
    indicator_id text not null,
    value_numeric double precision,
    value_text text,
    unit text,
    value_class text not null check (value_class in ('SOURCE','CALCULATED')),
    measurement_basis text not null,
    source_artifact_id uuid references clr_private.source_artifact(source_artifact_id),
    method_version text,
    period_start timestamptz,
    period_end timestamptz,
    quality_flag text not null default 'OK',
    null_reason text,
    run_id uuid references clr_private.processing_run(run_id),
    calculated_at timestamptz not null default now(),
    check (
      (value_numeric is not null and value_text is null and null_reason is null)
      or (value_numeric is null and value_text is not null and null_reason is null)
      or (value_numeric is null and value_text is null and null_reason is not null)
    )
);

create index if not exists asset_indicator_asset_idx
    on clr_private.asset_indicator (tenant_id, asset_location_id, indicator_id);

create table if not exists clr_private.portfolio_exposure (
    portfolio_exposure_id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references clr_private.tenant(tenant_id),
    portfolio_id text not null,
    exposure_id text not null,
    borrower_id text,
    asset_location_id uuid references clr_private.asset_location(asset_location_id),
    exposure_type text not null check (exposure_type in ('EAD','COLLATERAL_VALUE','SUM_INSURED','PRODUCTION_CAPACITY','OTHER')),
    amount numeric,
    currency text,
    valuation_date date,
    metadata jsonb not null default '{}'::jsonb,
    unique (tenant_id, portfolio_id, exposure_id, exposure_type)
);

create table if not exists clr_private.route_endpoint (
    route_endpoint_id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references clr_private.tenant(tenant_id),
    endpoint_type text not null,
    endpoint_name text,
    geom geometry(Point,4326) not null,
    source text not null,
    valid_from timestamptz,
    valid_to timestamptz
);

create table if not exists clr_private.asset_route_dependency (
    asset_route_dependency_id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references clr_private.tenant(tenant_id),
    asset_location_id uuid not null references clr_private.asset_location(asset_location_id),
    route_endpoint_id uuid not null references clr_private.route_endpoint(route_endpoint_id),
    relationship text not null check (relationship in ('PRIMARY','SECONDARY','ALTERNATIVE','UNKNOWN')),
    shipment_share numeric check (shipment_share is null or (shipment_share >= 0 and shipment_share <= 1)),
    valid_from timestamptz,
    valid_to timestamptz
);


create table if not exists clr_private.asset_indicator_source (
    asset_indicator_id bigint not null references clr_private.asset_indicator(asset_indicator_id) on delete cascade,
    source_artifact_id uuid not null references clr_private.source_artifact(source_artifact_id),
    source_role text not null check (source_role in (
        'PRIMARY','DEPTH','PERMANENT_WATER_MASK','SPURIOUS_DEPTH_MASK','TILE_EXTENTS','TARGET_SERIES','BASELINE_SERIES','SOURCE_PACKAGE','DEM_RASTER','GFM_EVENT_SERIES','FFWC_STATION_METADATA','FFWC_WATER_LEVEL','AUXILIARY'
    )),
    primary key (asset_indicator_id, source_artifact_id, source_role)
);

create index if not exists asset_indicator_source_artifact_idx
    on clr_private.asset_indicator_source(source_artifact_id, source_role);


create table if not exists clr_private.logistics_route_analysis (
    route_analysis_id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references clr_private.tenant(tenant_id),
    asset_route_dependency_id uuid not null references clr_private.asset_route_dependency(asset_route_dependency_id),
    run_id uuid references clr_private.processing_run(run_id),
    scenario_id text not null default 'BASELINE',
    origin_node_id bigint,
    destination_node_id bigint,
    origin_snap_distance_m double precision check(origin_snap_distance_m is null or origin_snap_distance_m >= 0),
    destination_snap_distance_m double precision check(destination_snap_distance_m is null or destination_snap_distance_m >= 0),
    baseline_length_m double precision check(baseline_length_m is null or baseline_length_m >= 0),
    hazard_exposed_length_m double precision check(hazard_exposed_length_m is null or hazard_exposed_length_m >= 0),
    hazard_exposed_share double precision check(hazard_exposed_share is null or (hazard_exposed_share >= 0 and hazard_exposed_share <= 1)),
    hazard_avoiding_length_m double precision check(hazard_avoiding_length_m is null or hazard_avoiding_length_m >= 0),
    hazard_detour_ratio double precision check(hazard_detour_ratio is null or hazard_detour_ratio >= 0),
    isolation_flag boolean,
    edge_disjoint_route_count integer,
    edge_disjoint_route_count_after_hazard integer,
    route_redundancy_loss integer,
    quality_flag text not null default 'OK',
    created_at timestamptz not null default now()
);

create index if not exists logistics_route_analysis_dependency_idx
    on clr_private.logistics_route_analysis(tenant_id, asset_route_dependency_id, scenario_id);

create table if not exists clr_private.logistics_route_analysis_source (
    route_analysis_id uuid not null references clr_private.logistics_route_analysis(route_analysis_id) on delete cascade,
    source_artifact_id uuid not null references clr_private.source_artifact(source_artifact_id),
    source_role text not null check(source_role in (
        'OSM_PBF','JRC_DEPTH','JRC_PERMANENT_WATER_MASK','JRC_SPURIOUS_DEPTH_MASK','JRC_TILE_EXTENTS','AUXILIARY'
    )),
    primary key(route_analysis_id, source_artifact_id, source_role)
);


create table if not exists clr_private.hydro_station (
    station_id text primary key,
    provider text not null,
    station_name text not null,
    river_name text,
    geom geometry(Point,4326) not null,
    danger_level_m double precision,
    source_artifact_id uuid references clr_private.source_artifact(source_artifact_id),
    metadata jsonb not null default '{}'::jsonb,
    updated_at timestamptz not null default now()
);

create table if not exists clr_private.hydro_observation (
    hydro_observation_id bigint generated always as identity primary key,
    provider text not null,
    station_id text not null references clr_private.hydro_station(station_id),
    observed_at timestamptz not null,
    water_level_m double precision not null,
    danger_level_m double precision,
    source_artifact_id uuid references clr_private.source_artifact(source_artifact_id),
    quality_flag text not null default 'OFFICIAL_SOURCE',
    unique(provider,station_id,observed_at)
);

create index if not exists hydro_observation_station_time_idx
    on clr_private.hydro_observation(station_id,observed_at);

create table if not exists clr_private.asset_hydro_station_link (
    asset_location_id uuid not null references clr_private.asset_location(asset_location_id),
    station_id text not null references clr_private.hydro_station(station_id),
    distance_km double precision not null check(distance_km >= 0),
    rank_order integer not null check(rank_order >= 1),
    method_version text not null,
    created_at timestamptz not null default now(),
    primary key(asset_location_id,station_id,method_version)
);

alter table clr_private.tenant enable row level security;
alter table clr_private.asset_location enable row level security;
alter table clr_private.source_artifact enable row level security;
alter table clr_private.processing_run enable row level security;
alter table clr_private.asset_indicator enable row level security;
alter table clr_private.asset_indicator_source enable row level security;
alter table clr_private.portfolio_exposure enable row level security;
alter table clr_private.route_endpoint enable row level security;
alter table clr_private.asset_route_dependency enable row level security;
alter table clr_private.logistics_route_analysis enable row level security;
alter table clr_private.logistics_route_analysis_source enable row level security;
alter table clr_private.hydro_station enable row level security;
alter table clr_private.hydro_observation enable row level security;
alter table clr_private.asset_hydro_station_link enable row level security;

revoke all on all tables in schema clr_private from public, anon, authenticated;
grant all on all tables in schema clr_private to service_role;
grant usage, select on all sequences in schema clr_private to service_role;

alter default privileges in schema clr_private revoke all on tables from public, anon, authenticated;
alter default privileges in schema clr_private grant all on tables to service_role;
alter default privileges in schema clr_private grant usage, select on sequences to service_role;
