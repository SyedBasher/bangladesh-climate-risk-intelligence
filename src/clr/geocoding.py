from __future__ import annotations
import re, unicodedata, json, time, hashlib
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

SITE_TYPES = {"industrial","factory","works","warehouse","commercial","retail","office","building","company","yes"}
LOCALITY_TYPES = {"city","town","village","hamlet","suburb","neighbourhood","administrative","road","residential","postcode"}

def norm(x: str | None) -> str:
    x = unicodedata.normalize("NFKC", x or "").casefold()
    x = re.sub(r"[\W_]+", " ", x, flags=re.UNICODE)
    return re.sub(r"\s+", " ", x).strip()

def build_queries(row: dict) -> list[dict]:
    if not (row.get("full_address_dife") or "").strip():
        return []
    address = row["full_address_dife"].strip()
    district = row["district_dife"].strip()
    upazila = row["upazila_dife"].strip()
    name = (row.get("name_en") or row.get("name_bn") or "").strip()
    queries = [
        {"q": f"{name}, {address}, {upazila}, {district}, Bangladesh", "query_level":"NAME_ADDRESS_ADMIN"},
        {"q": f"{address}, {upazila}, {district}, Bangladesh", "query_level":"ADDRESS_ADMIN"},
    ]
    seen=set(); out=[]
    for q in queries:
        k=norm(q["q"])
        if k not in seen:
            seen.add(k); out.append(q)
    return out

def _contains_admin(candidate: dict, expected: str) -> bool:
    if not expected:
        return True
    address = candidate.get("address") or {}
    hay = " ".join(str(v) for v in address.values()) + " " + str(candidate.get("display_name",""))
    return norm(expected) in norm(hay)

def candidate_grade(row: dict, candidate: dict, corroborated_site: bool=False) -> tuple[str, list[str]]:
    reasons=[]
    if not _contains_admin(candidate, row.get("district_dife","")):
        return "REJECTED_ADMIN_MISMATCH", ["district mismatch"]
    upazila_ok = _contains_admin(candidate, row.get("upazila_dife",""))
    reasons.append("upazila/locality compatible" if upazila_ok else "upazila not text-confirmed")
    cls = norm(candidate.get("class","")); typ = norm(candidate.get("type",""))
    site_like = any(t in (cls+" "+typ) for t in SITE_TYPES)
    locality_like = any(t in (cls+" "+typ) for t in LOCALITY_TYPES)
    candidate_name = norm(candidate.get("name") or candidate.get("display_name",""))
    source_name = norm(row.get("name_en") or row.get("name_bn",""))
    name_tokens = {t for t in source_name.split() if len(t) >= 4}
    name_match = bool(name_tokens) and len(name_tokens & set(candidate_name.split())) >= min(2,len(name_tokens))
    if name_match: reasons.append("name evidence")
    if corroborated_site: reasons.append("independent site-address corroboration")
    if locality_like and not site_like:
        return "LOCALITY_ONLY", reasons + ["candidate is locality/admin/road, not premises"]
    if site_like and upazila_ok and (name_match or corroborated_site):
        return "PROBABLE_SITE", reasons + ["site-like candidate"]
    return "AMBIGUOUS", reasons + ["insufficient site evidence"]

class NominatimPilotClient:
    """One-time public OSMF Nominatim pilot client; do not use public endpoint for recurring production."""
    def __init__(self, user_agent: str, cache_path: str|Path, base_url: str="https://nominatim.openstreetmap.org/search", min_interval_s: float=1.1):
        if not user_agent or "Mangrove" not in user_agent:
            raise ValueError("Provide a descriptive Mangrove User-Agent.")
        self.user_agent=user_agent; self.cache_path=Path(cache_path); self.base_url=base_url
        self.min_interval_s=max(1.1,float(min_interval_s)); self._last=0.0; self.cache={}
        if self.cache_path.exists():
            self.cache=json.loads(self.cache_path.read_text(encoding="utf-8"))
    def search(self, query: str, limit: int=5):
        key=hashlib.sha256(query.encode("utf-8")).hexdigest()
        if key in self.cache: return self.cache[key]
        wait=self.min_interval_s-(time.time()-self._last)
        if wait>0: time.sleep(wait)
        params=urlencode({"q":query,"format":"jsonv2","addressdetails":1,"namedetails":1,"countrycodes":"bd","limit":limit,"dedupe":1})
        req=Request(self.base_url+"?"+params,headers={"User-Agent":self.user_agent})
        with urlopen(req,timeout=30) as r: result=json.loads(r.read().decode("utf-8"))
        self._last=time.time(); self.cache[key]=result
        self.cache_path.parent.mkdir(parents=True,exist_ok=True)
        self.cache_path.write_text(json.dumps(self.cache,ensure_ascii=False,indent=2),encoding="utf-8")
        return result
