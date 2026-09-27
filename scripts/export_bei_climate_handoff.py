"""Export a public-safe Climate -> BEI handoff bundle.

Input must already contain aggregated national/division/district climate-context
records. This exporter deliberately rejects asset/site identifiers, coordinates,
risk scores, damage/loss estimates and bank-credit translations.

The resulting JSON bundle is designed to satisfy BEI_CLIMATE_HANDOFF_V1.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RELEASE_SCOPE = "BEI_PUBLIC_SAFE_ECONOMIC_CONTEXT"
ALLOWED_GEOS = {"national", "division", "district"}
ALLOWED_EVIDENCE = {
    "OFFICIAL", "OBSERVED", "SATELLITE_OBSERVED", "REANALYSIS", "CALCULATED"
}
ALLOWED_FAMILIES = {
    "heat_temperature_context",
    "rainfall_context",
    "observed_flood_context",
    "cyclone_context",
    "agriculture_vegetation_context",
    "population_or_economic_exposure_context",
}
ALLOWED_QUALITY = {"PASS", "LIMITED_USE", "NOT_AVAILABLE"}
BLOCKED_FIELDS = {
    "latitude", "longitude", "site_id", "asset_id", "facility_id",
    "private_address", "portfolio_id", "compound_risk_score",
    "vulnerability_score", "damage_estimate", "downtime_estimate",
    "production_loss_estimate", "pd", "lgd", "ecl",
    "insurance_loss_estimate",
}
REQUIRED = [
    "indicator_id", "indicator_family", "geography_level", "geo_id",
    "geo_name", "period", "value", "unit", "evidence_class",
    "source_family", "source_product", "source_vintage", "method_id",
    "quality_status", "lineage_sha256", "null_reason",
]


def require(ok: bool, msg: str) -> None:
    if not ok:
        raise ValueError(msg)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def validate_record(row: dict[str, Any]) -> None:
    require(isinstance(row, dict), "handoff record must be an object")
    missing = [key for key in REQUIRED if key not in row]
    require(not missing, f"missing required handoff fields: {missing}")
    leaked = [key for key in BLOCKED_FIELDS if row.get(key) not in (None, "")]
    require(not leaked, f"blocked private/risk fields present: {leaked}")
    require(row["geography_level"] in ALLOWED_GEOS, "unsupported geography level")
    require(row["evidence_class"] in ALLOWED_EVIDENCE, "unsupported evidence class")
    require(row["indicator_family"] in ALLOWED_FAMILIES, "unsupported indicator family")
    require(row["quality_status"] in ALLOWED_QUALITY, "unsupported quality status")
    require(
        isinstance(row["lineage_sha256"], str) and len(row["lineage_sha256"]) == 64,
        "lineage_sha256 must be a 64-character digest",
    )
    require(
        row["value"] is not None or bool(str(row["null_reason"]).strip()),
        "null values require explicit null_reason",
    )
    if row["geography_level"] == "district":
        require(bool(str(row["geo_id"]).strip()), "district records require geo_id")


def git_version(root: Path) -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except Exception:
        return "UNKNOWN"


def build_bundle(
    records: list[dict[str, Any]],
    release_id: str,
    *,
    source_engine_version: str,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    require(bool(release_id.strip()), "release_id is required")
    require(isinstance(records, list), "records must be a list")
    for row in records:
        validate_record(row)

    families = {row["indicator_family"] for row in records}
    require(len(families) <= 3, "first BEI handoff may contain at most three indicator families")

    generated = generated_at_utc or datetime.now(timezone.utc).isoformat(timespec="seconds")
    core = {
        "release_id": release_id,
        "generated_at_utc": generated,
        "source_engine_version": source_engine_version,
        "release_scope": RELEASE_SCOPE,
        "record_count": len(records),
        "records": records,
    }
    digest = hashlib.sha256(canonical_bytes(core)).hexdigest()
    return {**core, "bundle_sha256": digest}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path, help="JSON file containing aggregated records or {records:[...]}.")
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    records = payload["records"] if isinstance(payload, dict) and "records" in payload else payload
    root = Path(__file__).resolve().parents[1]
    bundle = build_bundle(
        records,
        args.release_id,
        source_engine_version=git_version(root),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(bundle, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": "SUCCESS",
        "release_id": bundle["release_id"],
        "record_count": bundle["record_count"],
        "bundle_sha256": bundle["bundle_sha256"],
        "output": str(args.output),
    }, indent=2))


if __name__ == "__main__":
    main()
