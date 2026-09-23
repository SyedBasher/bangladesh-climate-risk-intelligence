from __future__ import annotations

import hashlib
import re
from pathlib import PurePosixPath
from urllib.parse import urlparse

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def validate_sha256(value: str) -> str:
    value = str(value).lower()
    if not SHA256_RE.fullmatch(value):
        raise ValueError("Expected a lowercase 64-character SHA-256 digest")
    return value


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def source_object_key(provider: str, dataset: str, provider_version: str, sha256: str, filename: str) -> str:
    digest = validate_sha256(sha256)
    pieces = [provider, dataset, provider_version, filename]
    if any(not str(x).strip() for x in pieces):
        raise ValueError("Provider, dataset, version and filename are required")
    safe = []
    for value in pieces[:-1]:
        v = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value).strip())
        safe.append(v)
    name = PurePosixPath(filename).name
    if name != filename or name in {"", ".", ".."}:
        raise ValueError("filename must be a basename, not a path")
    return f"raw/{safe[0]}/{safe[1]}/{safe[2]}/{digest}/{name}"


def validate_private_object_uri(uri: str) -> str:
    parsed = urlparse(uri)
    if parsed.scheme not in {"s3", "r2", "supabase-storage"}:
        raise ValueError("Object URI must use an approved private object-store scheme")
    if not parsed.netloc:
        raise ValueError("Object URI must identify a bucket/container")
    return uri


def artifact_registration(
    *,
    source_id: str,
    provider: str,
    provider_version: str | None,
    object_uri: str,
    sha256: str,
    byte_size: int | None,
    retrieved_at: str,
    retrieval_status: str = "COMPLETE",
) -> dict:
    if retrieval_status not in {"COMPLETE", "PARTIAL", "FAILED", "BLOCKED"}:
        raise ValueError("Unsupported retrieval status")
    if byte_size is not None and int(byte_size) < 0:
        raise ValueError("byte_size cannot be negative")
    return {
        "source_id": source_id,
        "provider": provider,
        "provider_version": provider_version,
        "object_uri": validate_private_object_uri(object_uri),
        "sha256": validate_sha256(sha256),
        "byte_size": byte_size,
        "retrieved_at": retrieved_at,
        "retrieval_status": retrieval_status,
    }
