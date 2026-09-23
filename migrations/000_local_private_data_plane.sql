PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS workspace_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_artifact (
    source_artifact_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    provider_version TEXT,
    local_path TEXT NOT NULL,
    sha256 TEXT NOT NULL CHECK(length(sha256)=64),
    byte_size INTEGER CHECK(byte_size IS NULL OR byte_size >= 0),
    media_type TEXT,
    retrieved_at TEXT NOT NULL,
    valid_time_start TEXT,
    valid_time_end TEXT,
    request_manifest_path TEXT,
    request_manifest_sha256 TEXT,
    retrieval_status TEXT NOT NULL CHECK(retrieval_status IN ('COMPLETE','PARTIAL','FAILED','BLOCKED')),
    note TEXT,
    UNIQUE(source_id, sha256)
);

CREATE INDEX IF NOT EXISTS source_artifact_source_idx
    ON source_artifact(source_id, retrieved_at);

CREATE TABLE IF NOT EXISTS processing_run (
    run_id TEXT PRIMARY KEY,
    pipeline_name TEXT NOT NULL,
    pipeline_version TEXT NOT NULL,
    git_commit TEXT,
    profile_name TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL CHECK(status IN ('RUNNING','SUCCESS','FAILED','PARTIAL')),
    parameters_json TEXT NOT NULL DEFAULT '{}',
    error_summary TEXT
);

CREATE TABLE IF NOT EXISTS asset_location (
    asset_location_id TEXT PRIMARY KEY,
    tenant_key TEXT NOT NULL,
    external_system TEXT NOT NULL,
    external_id TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    latitude REAL NOT NULL CHECK(latitude BETWEEN -90 AND 90),
    longitude REAL NOT NULL CHECK(longitude BETWEEN -180 AND 180),
    coordinate_source TEXT NOT NULL,
    coordinate_precision_m REAL CHECK(coordinate_precision_m IS NULL OR coordinate_precision_m >= 0),
    site_identity_grade TEXT NOT NULL CHECK(site_identity_grade IN (
        'EXACT_SITE','PROBABLE_SITE','LOCALITY_ONLY','AMBIGUOUS','NO_MATCH','REJECTED_ADMIN_MISMATCH'
    )),
    coordinate_status TEXT NOT NULL CHECK(coordinate_status IN ('RESOLVED','PENDING','REJECTED')),
    valid_from TEXT,
    valid_to TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(tenant_key, external_system, external_id, valid_from)
);

CREATE INDEX IF NOT EXISTS asset_location_lookup_idx
    ON asset_location(tenant_key, external_system, external_id);

CREATE TABLE IF NOT EXISTS asset_indicator (
    asset_indicator_id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_key TEXT NOT NULL,
    asset_location_id TEXT NOT NULL REFERENCES asset_location(asset_location_id),
    indicator_id TEXT NOT NULL,
    value_numeric REAL,
    value_text TEXT,
    unit TEXT,
    value_class TEXT NOT NULL CHECK(value_class IN ('SOURCE','CALCULATED')),
    measurement_basis TEXT NOT NULL,
    source_artifact_id TEXT REFERENCES source_artifact(source_artifact_id),
    method_version TEXT,
    period_start TEXT,
    period_end TEXT,
    quality_flag TEXT NOT NULL DEFAULT 'OK',
    null_reason TEXT,
    run_id TEXT REFERENCES processing_run(run_id),
    calculated_at TEXT NOT NULL,
    CHECK(
        (value_numeric IS NOT NULL AND value_text IS NULL AND null_reason IS NULL)
        OR (value_numeric IS NULL AND value_text IS NOT NULL AND null_reason IS NULL)
        OR (value_numeric IS NULL AND value_text IS NULL AND null_reason IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS asset_indicator_lookup_idx
    ON asset_indicator(tenant_key, asset_location_id, indicator_id, period_end);

CREATE TABLE IF NOT EXISTS portfolio_exposure (
    portfolio_exposure_id TEXT PRIMARY KEY,
    tenant_key TEXT NOT NULL,
    portfolio_id TEXT NOT NULL,
    exposure_id TEXT NOT NULL,
    borrower_id TEXT,
    asset_location_id TEXT REFERENCES asset_location(asset_location_id),
    exposure_type TEXT NOT NULL CHECK(exposure_type IN (
        'EAD','COLLATERAL_VALUE','SUM_INSURED','PRODUCTION_CAPACITY','OTHER'
    )),
    amount REAL CHECK(amount IS NULL OR amount >= 0),
    currency TEXT,
    valuation_date TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(tenant_key, portfolio_id, exposure_id, exposure_type)
);

CREATE INDEX IF NOT EXISTS portfolio_exposure_lookup_idx
    ON portfolio_exposure(tenant_key, portfolio_id, exposure_type);

CREATE TABLE IF NOT EXISTS route_endpoint (
    route_endpoint_id TEXT PRIMARY KEY,
    tenant_key TEXT NOT NULL,
    endpoint_type TEXT NOT NULL,
    endpoint_name TEXT,
    latitude REAL NOT NULL CHECK(latitude BETWEEN -90 AND 90),
    longitude REAL NOT NULL CHECK(longitude BETWEEN -180 AND 180),
    source TEXT NOT NULL,
    valid_from TEXT,
    valid_to TEXT
);

CREATE TABLE IF NOT EXISTS asset_route_dependency (
    asset_route_dependency_id TEXT PRIMARY KEY,
    tenant_key TEXT NOT NULL,
    asset_location_id TEXT NOT NULL REFERENCES asset_location(asset_location_id),
    route_endpoint_id TEXT NOT NULL REFERENCES route_endpoint(route_endpoint_id),
    relationship TEXT NOT NULL CHECK(relationship IN ('PRIMARY','SECONDARY','ALTERNATIVE','UNKNOWN')),
    shipment_share REAL CHECK(shipment_share IS NULL OR (shipment_share >= 0 AND shipment_share <= 1)),
    valid_from TEXT,
    valid_to TEXT
);

CREATE TABLE IF NOT EXISTS parquet_dataset (
    parquet_dataset_id TEXT PRIMARY KEY,
    dataset_name TEXT NOT NULL,
    layer TEXT NOT NULL CHECK(layer IN ('NORMALIZED','INDICATORS')),
    relative_path TEXT NOT NULL,
    partition_spec_json TEXT NOT NULL DEFAULT '{}',
    row_count INTEGER CHECK(row_count IS NULL OR row_count >= 0),
    sha256 TEXT CHECK(sha256 IS NULL OR length(sha256)=64),
    created_at TEXT NOT NULL,
    run_id TEXT REFERENCES processing_run(run_id),
    UNIQUE(dataset_name, relative_path)
);

CREATE TABLE IF NOT EXISTS asset_indicator_source (
    asset_indicator_id INTEGER NOT NULL REFERENCES asset_indicator(asset_indicator_id) ON DELETE CASCADE,
    source_artifact_id TEXT NOT NULL REFERENCES source_artifact(source_artifact_id),
    source_role TEXT NOT NULL CHECK(source_role IN (
        'PRIMARY','DEPTH','PERMANENT_WATER_MASK','SPURIOUS_DEPTH_MASK','TILE_EXTENTS','TARGET_SERIES','BASELINE_SERIES','SOURCE_PACKAGE','DEM_RASTER','GFM_EVENT_SERIES','FFWC_STATION_METADATA','FFWC_WATER_LEVEL','IBTRACS_TRACK','AUXILIARY'
    )),
    PRIMARY KEY (asset_indicator_id, source_artifact_id, source_role)
);

CREATE INDEX IF NOT EXISTS asset_indicator_source_artifact_idx
    ON asset_indicator_source(source_artifact_id, source_role);


CREATE TABLE IF NOT EXISTS logistics_route_analysis (
    route_analysis_id TEXT PRIMARY KEY,
    tenant_key TEXT NOT NULL,
    asset_route_dependency_id TEXT NOT NULL REFERENCES asset_route_dependency(asset_route_dependency_id),
    run_id TEXT REFERENCES processing_run(run_id),
    scenario_id TEXT NOT NULL DEFAULT 'BASELINE',
    origin_node_id INTEGER,
    destination_node_id INTEGER,
    origin_snap_distance_m REAL CHECK(origin_snap_distance_m IS NULL OR origin_snap_distance_m >= 0),
    destination_snap_distance_m REAL CHECK(destination_snap_distance_m IS NULL OR destination_snap_distance_m >= 0),
    baseline_length_m REAL CHECK(baseline_length_m IS NULL OR baseline_length_m >= 0),
    hazard_exposed_length_m REAL CHECK(hazard_exposed_length_m IS NULL OR hazard_exposed_length_m >= 0),
    hazard_exposed_share REAL CHECK(hazard_exposed_share IS NULL OR (hazard_exposed_share >= 0 AND hazard_exposed_share <= 1)),
    hazard_avoiding_length_m REAL CHECK(hazard_avoiding_length_m IS NULL OR hazard_avoiding_length_m >= 0),
    hazard_detour_ratio REAL CHECK(hazard_detour_ratio IS NULL OR hazard_detour_ratio >= 0),
    isolation_flag INTEGER CHECK(isolation_flag IS NULL OR isolation_flag IN (0,1)),
    edge_disjoint_route_count INTEGER CHECK(edge_disjoint_route_count IS NULL OR edge_disjoint_route_count >= 0),
    edge_disjoint_route_count_after_hazard INTEGER CHECK(edge_disjoint_route_count_after_hazard IS NULL OR edge_disjoint_route_count_after_hazard >= 0),
    route_redundancy_loss INTEGER,
    quality_flag TEXT NOT NULL DEFAULT 'OK',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS logistics_route_analysis_dependency_idx
    ON logistics_route_analysis(tenant_key, asset_route_dependency_id, scenario_id);

CREATE TABLE IF NOT EXISTS logistics_route_analysis_source (
    route_analysis_id TEXT NOT NULL REFERENCES logistics_route_analysis(route_analysis_id) ON DELETE CASCADE,
    source_artifact_id TEXT NOT NULL REFERENCES source_artifact(source_artifact_id),
    source_role TEXT NOT NULL CHECK(source_role IN (
        'OSM_PBF','JRC_DEPTH','JRC_PERMANENT_WATER_MASK','JRC_SPURIOUS_DEPTH_MASK','JRC_TILE_EXTENTS','AUXILIARY'
    )),
    PRIMARY KEY(route_analysis_id, source_artifact_id, source_role)
);


CREATE TABLE IF NOT EXISTS hydro_station (
    station_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    station_name TEXT NOT NULL,
    river_name TEXT,
    latitude REAL NOT NULL CHECK(latitude BETWEEN -90 AND 90),
    longitude REAL NOT NULL CHECK(longitude BETWEEN -180 AND 180),
    danger_level_m REAL,
    source_artifact_id TEXT REFERENCES source_artifact(source_artifact_id),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS hydro_observation (
    hydro_observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    station_id TEXT NOT NULL REFERENCES hydro_station(station_id),
    observed_at TEXT NOT NULL,
    water_level_m REAL NOT NULL,
    danger_level_m REAL,
    source_artifact_id TEXT REFERENCES source_artifact(source_artifact_id),
    quality_flag TEXT NOT NULL DEFAULT 'OFFICIAL_SOURCE',
    UNIQUE(provider,station_id,observed_at)
);

CREATE INDEX IF NOT EXISTS hydro_observation_station_time_idx
    ON hydro_observation(station_id,observed_at);

CREATE TABLE IF NOT EXISTS asset_hydro_station_link (
    asset_location_id TEXT NOT NULL REFERENCES asset_location(asset_location_id),
    station_id TEXT NOT NULL REFERENCES hydro_station(station_id),
    distance_km REAL NOT NULL CHECK(distance_km >= 0),
    rank_order INTEGER NOT NULL CHECK(rank_order >= 1),
    method_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(asset_location_id,station_id,method_version)
);
