import pytest

from clr.private_plane import (
    artifact_registration,
    sha256_bytes,
    source_object_key,
    validate_private_object_uri,
)


def test_source_object_key_is_content_addressed():
    digest = sha256_bytes(b"synthetic source artifact")
    key = source_object_key("ECMWF", "ERA5-Land", "2026-09", digest, "heat.nc")
    assert key == f"raw/ECMWF/ERA5-Land/2026-09/{digest}/heat.nc"


def test_source_object_key_rejects_path_filename():
    digest = sha256_bytes(b"x")
    with pytest.raises(ValueError):
        source_object_key("JRC", "flood", "2.1.2", digest, "../secret.tif")


def test_private_uri_rejects_web_url():
    with pytest.raises(ValueError):
        validate_private_object_uri("https://example.com/public/file.tif")


def test_artifact_registration_preserves_hash_and_status():
    digest = sha256_bytes(b"synthetic")
    row = artifact_registration(
        source_id="ERA5L_DAILY",
        provider="Copernicus CDS",
        provider_version="synthetic-v1",
        object_uri="s3://climate-private/raw/example.nc",
        sha256=digest,
        byte_size=123,
        retrieved_at="2026-09-23T00:00:00Z",
    )
    assert row["sha256"] == digest
    assert row["retrieval_status"] == "COMPLETE"
