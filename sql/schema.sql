CREATE EXTENSION IF NOT EXISTS postgis;

CREATE SCHEMA IF NOT EXISTS clr;

CREATE TABLE IF NOT EXISTS clr.source_dataset (
    source_id text PRIMARY KEY,
    dataset_name text NOT NULL,
    provider text NOT NULL,
    provider_class text NOT NULL CHECK (provider_class IN ('OFFICIAL','PUBLIC_SERVICE','RESEARCH','OPEN_COMMUNITY')),
    measurement_basis text NOT NULL,
    source_url text NOT NULL,
    licence_text text,
    source_methodology text,
    spatial_resolution_text text,
    temporal_resolution_text text,
    access_method text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS clr.source_vintage (
    source_vintage_id bigserial PRIMARY KEY,
    source_id text NOT NULL REFERENCES clr.source_dataset(source_id),
    provider_version text,
    valid_time_start timestamptz,
    valid_time_end timestamptz,
    retrieved_at timestamptz NOT NULL,
    content_hash text,
    storage_uri text,
    retrieval_status text NOT NULL CHECK (retrieval_status IN ('SUCCESS','PARTIAL','FAILED','BLOCKED')),
    retrieval_note text,
    UNIQUE (source_id, provider_version, retrieved_at)
);

CREATE TABLE IF NOT EXISTS clr.admin_unit (
    admin_id text NOT NULL,
    admin_level smallint NOT NULL CHECK (admin_level BETWEEN 0 AND 4),
    bbs_code text,
    name_en text NOT NULL,
    name_bn text,
    parent_admin_id text,
    geometry_vintage text NOT NULL,
    geom geometry(MultiPolygon,4326) NOT NULL,
    PRIMARY KEY (admin_id, geometry_vintage)
);

CREATE INDEX IF NOT EXISTS admin_geom_gix ON clr.admin_unit USING gist (geom);

CREATE TABLE IF NOT EXISTS clr.asset_location (
    asset_location_id uuid PRIMARY KEY,
    external_system text NOT NULL,
    external_id text NOT NULL,
    asset_type text NOT NULL,
    geom geometry(Point,4326) NOT NULL,
    coordinate_source text NOT NULL,
    coordinate_precision_m numeric,
    geocode_method text,
    geocode_confidence numeric CHECK (geocode_confidence IS NULL OR geocode_confidence BETWEEN 0 AND 1),
    spatial_match_status text NOT NULL CHECK (spatial_match_status IN ('UNMATCHED','MATCHED','AMBIGUOUS','REJECTED')),
    valid_from timestamptz,
    valid_to timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (external_system, external_id, valid_from)
);

CREATE INDEX IF NOT EXISTS asset_geom_gix ON clr.asset_location USING gist (geom);

CREATE TABLE IF NOT EXISTS clr.asset_admin_match (
    asset_location_id uuid NOT NULL REFERENCES clr.asset_location(asset_location_id),
    geometry_vintage text NOT NULL,
    admin_level smallint NOT NULL,
    admin_id text,
    match_method text NOT NULL,
    boundary_distance_m numeric,
    match_confidence numeric CHECK (match_confidence IS NULL OR match_confidence BETWEEN 0 AND 1),
    match_status text NOT NULL CHECK (match_status IN ('MATCHED','AMBIGUOUS','NO_MATCH','REJECTED')),
    matched_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (asset_location_id, geometry_vintage, admin_level)
);

CREATE TABLE IF NOT EXISTS clr.indicator_definition (
    indicator_id text PRIMARY KEY,
    domain text NOT NULL,
    indicator_name text NOT NULL,
    unit text,
    value_class text NOT NULL CHECK (value_class IN ('SOURCE','CALCULATED')),
    measurement_basis text NOT NULL,
    method_version text,
    method_description text NOT NULL,
    null_policy text NOT NULL,
    spatial_support text,
    temporal_support text
);

CREATE TABLE IF NOT EXISTS clr.asset_indicator (
    asset_location_id uuid NOT NULL REFERENCES clr.asset_location(asset_location_id),
    indicator_id text NOT NULL REFERENCES clr.indicator_definition(indicator_id),
    source_vintage_id bigint REFERENCES clr.source_vintage(source_vintage_id),
    period_start timestamptz,
    period_end timestamptz,
    value_numeric double precision,
    value_text text,
    unit text,
    method_version text,
    quality_flag text,
    null_reason text,
    calculated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (
      (value_numeric IS NOT NULL AND value_text IS NULL AND null_reason IS NULL)
      OR (value_numeric IS NULL AND value_text IS NOT NULL AND null_reason IS NULL)
      OR (value_numeric IS NULL AND value_text IS NULL AND null_reason IS NOT NULL)
    ),
    PRIMARY KEY (asset_location_id, indicator_id, source_vintage_id, period_start, period_end)
);

CREATE TABLE IF NOT EXISTS clr.admin_indicator (
    admin_id text NOT NULL,
    geometry_vintage text NOT NULL,
    admin_level smallint NOT NULL,
    indicator_id text NOT NULL REFERENCES clr.indicator_definition(indicator_id),
    source_vintage_id bigint REFERENCES clr.source_vintage(source_vintage_id),
    period_start timestamptz,
    period_end timestamptz,
    aggregation_method text NOT NULL,
    value_numeric double precision,
    unit text,
    quality_flag text,
    null_reason text,
    calculated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS clr.processing_run (
    run_id uuid PRIMARY KEY,
    pipeline_name text NOT NULL,
    pipeline_version text NOT NULL,
    git_commit text,
    started_at timestamptz NOT NULL,
    finished_at timestamptz,
    status text NOT NULL CHECK (status IN ('RUNNING','SUCCESS','FAILED','PARTIAL')),
    parameters jsonb NOT NULL DEFAULT '{}'::jsonb,
    error_summary text
);

CREATE TABLE IF NOT EXISTS clr.asset_indicator_lineage (
    run_id uuid NOT NULL REFERENCES clr.processing_run(run_id),
    asset_location_id uuid NOT NULL REFERENCES clr.asset_location(asset_location_id),
    indicator_id text NOT NULL REFERENCES clr.indicator_definition(indicator_id),
    source_vintage_id bigint REFERENCES clr.source_vintage(source_vintage_id),
    PRIMARY KEY (run_id, asset_location_id, indicator_id, source_vintage_id)
);
