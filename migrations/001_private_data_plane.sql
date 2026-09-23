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
        'PRIMARY','DEPTH','PERMANENT_WATER_MASK','SPURIOUS_DEPTH_MASK','TILE_EXTENTS','TARGET_SERIES','BASELINE_SERIES','AUXILIARY'
    )),
    primary key (asset_indicator_id, source_artifact_id, source_role)
);

create index if not exists asset_indicator_source_artifact_idx
    on clr_private.asset_indicator_source(source_artifact_id, source_role);

alter table clr_private.tenant enable row level security;
alter table clr_private.asset_location enable row level security;
alter table clr_private.source_artifact enable row level security;
alter table clr_private.processing_run enable row level security;
alter table clr_private.asset_indicator enable row level security;
alter table clr_private.asset_indicator_source enable row level security;
alter table clr_private.portfolio_exposure enable row level security;
alter table clr_private.route_endpoint enable row level security;
alter table clr_private.asset_route_dependency enable row level security;

revoke all on all tables in schema clr_private from public, anon, authenticated;
grant all on all tables in schema clr_private to service_role;
grant usage, select on all sequences in schema clr_private to service_role;

alter default privileges in schema clr_private revoke all on tables from public, anon, authenticated;
alter default privileges in schema clr_private grant all on tables to service_role;
alter default privileges in schema clr_private grant usage, select on sequences to service_role;
