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
        'PRIMARY','DEPTH','PERMANENT_WATER_MASK','SPURIOUS_DEPTH_MASK','TILE_EXTENTS','TARGET_SERIES','BASELINE_SERIES','SOURCE_PACKAGE','DEM_RASTER','AUXILIARY'
    )),
    PRIMARY KEY (asset_indicator_id, source_artifact_id, source_role)
);

CREATE INDEX IF NOT EXISTS asset_indicator_source_artifact_idx
    ON asset_indicator_source(source_artifact_id, source_role);
