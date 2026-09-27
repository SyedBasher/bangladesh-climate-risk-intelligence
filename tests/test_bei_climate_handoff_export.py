from scripts.export_bei_climate_handoff import build_bundle


def row(**overrides):
    base={
        "indicator_id":"RAIN_ANOMALY",
        "indicator_family":"rainfall_context",
        "geography_level":"national",
        "geo_id":"BGD",
        "geo_name":"Bangladesh",
        "period":"2025",
        "value":1.25,
        "unit":"standardized anomaly",
        "evidence_class":"CALCULATED",
        "source_family":"CHIRPS",
        "source_product":"CHIRPS_V3_FINAL_RNL",
        "source_vintage":"2025",
        "method_id":"rainfall_anomaly_v1",
        "quality_status":"PASS",
        "lineage_sha256":"a"*64,
        "null_reason":"",
    }
    base.update(overrides)
    return base


def test_build_public_safe_bundle():
    bundle=build_bundle([row()],"BEI_CLIMATE_TEST",source_engine_version="abc123",generated_at_utc="2026-09-28T00:00:00+00:00")
    assert bundle["release_scope"]=="BEI_PUBLIC_SAFE_ECONOMIC_CONTEXT"
    assert bundle["record_count"]==1
    assert len(bundle["bundle_sha256"])==64


def test_private_fields_rejected():
    try:
        build_bundle([row(latitude=23.8)],"BAD",source_engine_version="abc")
    except ValueError as exc:
        assert "blocked private/risk fields" in str(exc)
    else:
        raise AssertionError("private coordinate was not rejected")


def test_null_requires_reason():
    try:
        build_bundle([row(value=None,null_reason="")],"BAD",source_engine_version="abc")
    except ValueError as exc:
        assert "null values require explicit null_reason" in str(exc)
    else:
        raise AssertionError("silent null was not rejected")


def test_first_release_limited_to_three_families():
    rows=[
        row(indicator_family="rainfall_context"),
        row(indicator_family="heat_temperature_context",indicator_id="HEAT"),
        row(indicator_family="observed_flood_context",indicator_id="FLOOD"),
        row(indicator_family="cyclone_context",indicator_id="CYCLONE"),
    ]
    try:
        build_bundle(rows,"BAD",source_engine_version="abc")
    except ValueError as exc:
        assert "at most three indicator families" in str(exc)
    else:
        raise AssertionError("family limit was not enforced")
