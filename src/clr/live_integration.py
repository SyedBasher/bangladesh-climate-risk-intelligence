from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable
import hashlib, json, os, shutil
import pandas as pd

FINAL_STATES={"COMPLETE","NOT_REQUESTED"}
FAIL_STATES={"CREDENTIAL_REQUIRED","NETWORK_REQUIRED","BLOCKED_RUNTIME","FAILED","PARTIAL","INVALID","MISSING"}

@dataclass
class SourceState:
    source_id: str
    status: str
    production_class: str
    artifact_path: str | None = None
    sha256: str | None = None
    retrieval_parameters_path: str | None = None
    note: str | None = None
    def to_dict(self): return asdict(self)

def sha256_file(path: str | Path) -> str:
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""): h.update(chunk)
    return h.hexdigest()

def required_source_ids(profile: dict) -> set[str]: return set(profile.get("required_sources",[]))

def can_publish(profile: dict, states: Iterable[SourceState]) -> tuple[bool,list[str]]:
    state_map={s.source_id:s for s in states}; missing=[]
    for source_id in required_source_ids(profile):
        s=state_map.get(source_id)
        if s is None or s.status!="COMPLETE": missing.append(source_id)
        elif s.production_class=="VALIDATION_ONLY" and not profile.get("allow_validation_gateway_values",False): missing.append(source_id)
    return (len(missing)==0,sorted(missing))

def enforce_atomic_profile(profile: dict, states: Iterable[SourceState]):
    ok,missing=can_publish(profile,states)
    if profile.get("publish_mode")=="ATOMIC" and not ok:
        raise RuntimeError("Atomic profile cannot publish; incomplete required sources: "+", ".join(missing))
    return ok,missing

def validate_indicator_rows(df: pd.DataFrame, profile: dict, states: Iterable[SourceState]) -> None:
    required={"external_id","indicator_id","value_class","measurement_basis","source_id","source_vintage"}
    missing=required-set(df.columns)
    if missing: raise ValueError(f"Indicator table missing required fields: {sorted(missing)}")
    state_map={s.source_id:s for s in states}
    for sid in set(df["source_id"].dropna()):
        if sid not in state_map or state_map[sid].status!="COMPLETE": raise ValueError(f"Indicator rows reference incomplete source {sid}")
        if state_map[sid].production_class=="VALIDATION_ONLY" and not profile.get("allow_validation_gateway_values",False):
            raise ValueError(f"Validation-only source {sid} cannot enter production output")

def atomic_publish(indicator_csv: str|Path, destination: str|Path, profile: dict, states: Iterable[SourceState]):
    enforce_atomic_profile(profile,states)
    df=pd.read_csv(indicator_csv); validate_indicator_rows(df,profile,states)
    dest=Path(destination); dest.parent.mkdir(parents=True,exist_ok=True)
    tmp=dest.with_suffix(dest.suffix+".tmp"); shutil.copyfile(indicator_csv,tmp); tmp.replace(dest)
    return dest

def preflight_environment() -> dict:
    home=Path.home()
    return {
        "cdsapi_module_installed": __import__("importlib").util.find_spec("cdsapi") is not None,
        "cds_credentials_file_exists": (home/".cdsapirc").exists(),
        "cds_key_env_exists": bool(os.getenv("CDSAPI_KEY")),
        "cdse_username_env_exists": bool(os.getenv("CDSE_USERNAME")),
        "cdse_password_env_exists": bool(os.getenv("CDSE_PASSWORD")),
        "gfm_username_env_exists": bool(os.getenv("GFM_USERNAME")),
        "gfm_password_env_exists": bool(os.getenv("GFM_PASSWORD")),
        "osmium_module_installed": __import__("importlib").util.find_spec("osmium") is not None,
        "rasterio_module_installed": __import__("importlib").util.find_spec("rasterio") is not None,
        "networkx_module_installed": __import__("importlib").util.find_spec("networkx") is not None,
    }

def write_states(states, path):
    Path(path).write_text(json.dumps([s.to_dict() for s in states],indent=2),encoding="utf-8")
