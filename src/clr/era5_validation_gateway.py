"""
Secondary validation gateway only.

Open-Meteo exposes ERA5-Land point histories, but Mangrove production provenance should remain
the official ECMWF/Copernicus CDS/ARCO source chain. Commercial deployment must comply with
Open-Meteo commercial terms if this gateway is used.
"""
from __future__ import annotations
from urllib.parse import urlencode

def era5_land_validation_url(lat: float, lon: float, start_date: str, end_date: str) -> str:
    params = {
        "latitude":lat,
        "longitude":lon,
        "start_date":start_date,
        "end_date":end_date,
        "daily":"temperature_2m_max,temperature_2m_min,apparent_temperature_max",
        "timezone":"Asia/Dhaka",
        "models":"era5_land",
    }
    return "https://archive-api.open-meteo.com/v1/archive?" + urlencode(params)
