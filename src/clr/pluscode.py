from __future__ import annotations

ALPHABET = "23456789CFGHJMPQRVWX"
SEPARATOR = "+"
SEPARATOR_POSITION = 8
PAIR_RESOLUTIONS = [20.0, 1.0, 0.05, 0.0025, 0.000125]

def _clip_lat(lat: float) -> float:
    return min(90.0, max(-90.0, float(lat)))

def _norm_lon(lon: float) -> float:
    lon=float(lon)
    while lon < -180.0: lon += 360.0
    while lon >= 180.0: lon -= 360.0
    return lon

def encode_pair_section(lat: float, lon: float, code_length: int=10) -> str:
    lat=_clip_lat(lat); lon=_norm_lon(lon)
    if lat == 90.0: lat -= PAIR_RESOLUTIONS[-1]
    lat += 90.0; lon += 180.0; chars=[]
    for res in PAIR_RESOLUTIONS:
        if len(chars) >= code_length: break
        li=min(19,int(lat/res)); oi=min(19,int(lon/res)); chars.extend([ALPHABET[li],ALPHABET[oi]])
        lat -= li*res; lon -= oi*res
    raw="".join(chars[:code_length]); return raw[:SEPARATOR_POSITION]+"+"+raw[SEPARATOR_POSITION:]

def decode_full(code: str) -> dict:
    clean=code.upper().replace("+","").replace("0","")
    if len(clean)<2: raise ValueError("OLC code too short")
    lat_lo=-90.0; lon_lo=-180.0; pair_len=min(len(clean),10); lat_res=lon_res=None; i=0; pair_idx=0
    while i+1<pair_len:
        res=PAIR_RESOLUTIONS[pair_idx]; lat_lo+=ALPHABET.index(clean[i])*res; lon_lo+=ALPHABET.index(clean[i+1])*res
        lat_res=lon_res=res; i+=2; pair_idx+=1
    if len(clean)>10:
        lat_res=PAIR_RESOLUTIONS[-1]; lon_res=PAIR_RESOLUTIONS[-1]
        for ch in clean[10:]:
            lat_res/=5.0; lon_res/=4.0; idx=ALPHABET.index(ch); row=idx//4; col=idx%4
            lat_lo+=row*lat_res; lon_lo+=col*lon_res
    return {"lat_lo":lat_lo,"lon_lo":lon_lo,"lat_hi":lat_lo+lat_res,"lon_hi":lon_lo+lon_res,"lat_center":lat_lo+lat_res/2.0,"lon_center":lon_lo+lon_res/2.0,"lat_resolution_deg":lat_res,"lon_resolution_deg":lon_res}

def recover_short(short_code: str, reference_lat: float, reference_lon: float) -> dict:
    short=short_code.upper(); sep=short.find("+")
    if sep<0 or sep>=SEPARATOR_POSITION: raise ValueError("Expected a short Plus Code")
    missing=SEPARATOR_POSITION-sep
    if missing%2: raise ValueError("Invalid short-code prefix length")
    ref_full=encode_pair_section(reference_lat,reference_lon,10); full_code=ref_full[:missing]+short; area=decode_full(full_code)
    lat=area["lat_center"]; lon=area["lon_center"]; missing_pairs=missing//2; recovery_resolution=20 ** (2-missing_pairs); half=recovery_resolution/2.0
    if reference_lat+half<lat and lat-recovery_resolution>=-90: lat-=recovery_resolution
    elif reference_lat-half>lat and lat+recovery_resolution<=90: lat+=recovery_resolution
    if reference_lon+half<lon: lon-=recovery_resolution
    elif reference_lon-half>lon: lon+=recovery_resolution
    area.update({"full_code":full_code,"recovered_lat":lat,"recovered_lon":lon,"recovery_resolution_deg":recovery_resolution}); return area
