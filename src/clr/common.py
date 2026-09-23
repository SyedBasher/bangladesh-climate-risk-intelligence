from dataclasses import dataclass, asdict
from typing import Optional, Any
import hashlib
from pathlib import Path

@dataclass(frozen=True)
class IndicatorResult:
    indicator_id: str
    value: Optional[float]
    unit: str
    value_class: str
    measurement_basis: str
    quality_flag: str = "OK"
    null_reason: Optional[str] = None
    method_version: str = "0.2.0"
    source_vintage: Optional[str] = None

    def to_dict(self):
        return asdict(self)

def sha256_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()

def require_coordinate(lat: float, lon: float) -> None:
    if lat is None or lon is None:
        raise ValueError("Coordinates are required; fail closed.")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("Coordinate outside valid WGS84 range.")
