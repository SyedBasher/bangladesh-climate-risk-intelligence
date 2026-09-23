from __future__ import annotations
from pathlib import Path
from urllib.request import Request, urlopen
import time
from .common import sha256_file

def download_file(url: str, destination: str | Path, timeout: int = 12, retries: int = 2) -> dict:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix(destination.suffix + ".part")
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            req = Request(url, headers={"User-Agent":"Mangrove-Climate-Risk-Pilot/0.3"})
            with urlopen(req, timeout=timeout) as r, open(tmp, "wb") as f:
                total = 0
                while True:
                    chunk = r.read(1024 * 1024)
                    if not chunk:
                        break
                    f.write(chunk); total += len(chunk)
            tmp.replace(destination)
            return {"status":"SUCCESS","url":url,"path":str(destination),"bytes":total,"sha256":sha256_file(destination),"error":None}
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
            if tmp.exists():
                tmp.unlink()
            if attempt < retries:
                time.sleep(1)
    return {"status":"FAILED","url":url,"path":str(destination),"bytes":None,"sha256":None,"error":last_error}
