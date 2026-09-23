from __future__ import annotations
from pathlib import Path
import hashlib, json, datetime

def sha256_file(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""): h.update(chunk)
    return h.hexdigest()

def build_vintage(source_id, artifact_path, request_params=None, provider_version=None, note=None):
    p=Path(artifact_path)
    if not p.exists(): raise FileNotFoundError(p)
    return {"source_id":source_id,"provider_version":provider_version,"retrieved_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),"artifact_path":str(p),"bytes":p.stat().st_size,"sha256":sha256_file(p),"request_params":request_params,"note":note}

def write_vintage(vintage,path):
    Path(path).write_text(json.dumps(vintage,indent=2),encoding="utf-8")
