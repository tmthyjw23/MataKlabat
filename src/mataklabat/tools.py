"""Read-only tools for the incident agent (Spec §9, ARCHITECTURE §7.2).

Every tool returns plain JSON-able data. Missing data is reported as
{"status": "unavailable", ...} so the agent writes "tidak tersedia" instead of
inventing numbers.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import math
from typing import Any, Callable

import requests

from mataklabat.config import Settings
from mataklabat.prompts import compass_name

log = logging.getLogger(__name__)

EARTH_RADIUS_KM = 6371.0
SPREAD_HALF_ANGLE_DEG = 45.0
SPREAD_MAX_KM = 8.0
FIRMS_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/VIIRS_SNPP_NRT/{bbox}/1"


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def spread_direction(wind_from_deg: float) -> float:
    """Wind FROM X degrees pushes fire TOWARD (X + 180) degrees."""
    return (wind_from_deg + 180.0) % 360.0


def angle_diff(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def fetch_firms(key: str, west: float, south: float, east: float, north: float) -> str:
    url = FIRMS_URL.format(key=key, bbox=f"{west:.4f},{south:.4f},{east:.4f},{north:.4f}")
    resp = requests.get(url, timeout=20)
    resp.raise_for_status()
    return resp.text


class IncidentTools:
    def __init__(
        self,
        settings: Settings,
        risk_provider: Callable[[], dict | None],
        recent_events: Callable[[str, int], list[dict]] = lambda camera_id, minutes: [],
        firms_fetch: Callable[..., str] = fetch_firms,
    ):
        self.settings = settings
        self.risk_provider = risk_provider
        self.recent_events = recent_events
        self.firms_fetch = firms_fetch

    # --- tools ----------------------------------------------------------------------------------

    def get_weather(self, lat: float, lon: float) -> dict[str, Any]:
        risk = self.risk_provider()
        if not risk:
            return {"status": "unavailable", "reason": "data cuaca belum tersedia"}
        now = risk.get("now") or {}
        return {
            "source": "Open-Meteo (data model, titik referensi Puncak Klabat)",
            "temperature_c": now.get("temp_c"),
            "humidity_pct": now.get("rh_pct"),
            "wind_kmh": now.get("wind_kmh"),
            "wind_from_deg": now.get("wind_dir_deg"),
            "wind_from": None if now.get("wind_dir_deg") is None else compass_name(now["wind_dir_deg"]),
            "area_risk_level": risk["level"],
            "area_risk_driver": risk["driver_text"],
            "fwi": risk["codes"]["fwi"],
            "drought_code": risk["codes"]["dc"],
            "days_without_rain": risk["days_without_rain"],
        }

    def get_satellite_hotspots(self, lat: float, lon: float, radius_km: float = 10.0) -> dict[str, Any]:
        key = self.settings.firms_map_key
        if not key:
            return {"status": "unavailable", "reason": "FIRMS_MAP_KEY belum diisi"}
        dlat = radius_km / 111.0
        dlon = radius_km / (111.0 * max(0.1, math.cos(math.radians(lat))))
        try:
            text = self.firms_fetch(key, lon - dlon, lat - dlat, lon + dlon, lat + dlat)
        except Exception as exc:  # noqa: BLE001
            return {"status": "unavailable", "reason": f"NASA FIRMS tidak bisa diakses ({type(exc).__name__})"}
        hotspots = []
        for row in csv.DictReader(io.StringIO(text)):
            try:
                hlat, hlon = float(row["latitude"]), float(row["longitude"])
            except (KeyError, ValueError):
                continue
            dist = haversine_km(lat, lon, hlat, hlon)
            if dist <= radius_km:
                hotspots.append({
                    "lat": hlat, "lon": hlon, "distance_km": round(dist, 1),
                    "confidence": row.get("confidence"),
                    "time_utc": f"{row.get('acq_date', '')} {row.get('acq_time', '')}".strip(),
                })
        hotspots.sort(key=lambda h: h["distance_km"])
        return {"status": "ok", "source": "NASA FIRMS VIIRS (24 jam)", "count": len(hotspots), "hotspots": hotspots[:10]}

    def estimate_spread(self, camera_id: str, wind_dir_deg: float, wind_kmh: float) -> dict[str, Any]:
        cam = self.settings.camera(camera_id)
        toward = spread_direction(wind_dir_deg)
        threatened = []
        for village in self.settings.resources.villages:
            dist = haversine_km(cam.lat, cam.lon, village.lat, village.lon)
            brg = bearing_deg(cam.lat, cam.lon, village.lat, village.lon)
            if dist <= SPREAD_MAX_KM and angle_diff(brg, toward) <= SPREAD_HALF_ANGLE_DEG:
                threatened.append({"name": village.name, "distance_km": round(dist, 1), "bearing": compass_name(brg)})
        threatened.sort(key=lambda v: v["distance_km"])
        return {
            "wind_from_deg": round(wind_dir_deg),
            "spread_toward_deg": round(toward),
            "spread_toward": compass_name(toward),
            "wind_kmh": wind_kmh,
            "note": "angin lemah, sebaran bisa ke segala arah" if wind_kmh < 5 else None,
            "villages_in_path": threatened,
            "method": f"desa dalam sektor ±{SPREAD_HALF_ANGLE_DEG:.0f}° searah angin, ≤ {SPREAD_MAX_KM:.0f} km, koordinat perkiraan",
        }

    def find_nearest_resources(self, lat: float, lon: float, kind: str | None = None) -> dict[str, Any]:
        items = [r for r in self.settings.resources.resources if kind in (None, "", r.kind)]
        ranked = sorted(items, key=lambda r: haversine_km(lat, lon, r.lat, r.lon))[:3]
        return {
            "resources": [
                {
                    "name": r.name,
                    "kind": r.kind,
                    "distance_km": round(haversine_km(lat, lon, r.lat, r.lon), 1),
                    "contact": "belum diisi" if r.contact in ("", "ISI_SENDIRI") else r.contact,
                }
                for r in ranked
            ]
        }

    def get_recent_events(self, camera_id: str, minutes: int = 30) -> dict[str, Any]:
        rows = self.recent_events(camera_id, minutes)
        levels: dict[str, int] = {}
        for r in rows:
            levels[r["level"]] = levels.get(r["level"], 0) + 1
        changes = [
            {"ts": r["ts"], "level": r["level"], "rule": r["rule"]}
            for prev, r in zip([None, *rows], rows)
            if prev is None or prev["level"] != r["level"]
        ]
        return {"minutes": minutes, "events": len(rows), "per_level": levels, "level_changes": changes[-10:]}

    # --- dispatch ---------------------------------------------------------------------------

    def call(self, name: str, arguments: str | dict) -> dict[str, Any]:
        handler = getattr(self, name, None) if name in TOOL_NAMES else None
        if handler is None:
            return {"error": f"tool tidak dikenal: {name}"}
        try:
            args = json.loads(arguments) if isinstance(arguments, str) else dict(arguments)
            return handler(**args)
        except Exception as exc:  # noqa: BLE001 - errors go back to the model as data
            return {"error": f"{type(exc).__name__}: {exc}"}


def _fn(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


_NUM = {"type": "number"}
TOOL_SCHEMAS = [
    _fn("get_weather", "Cuaca terkini dan risiko kebakaran kawasan (FWI/FDRS).",
        {"lat": _NUM, "lon": _NUM}, ["lat", "lon"]),
    _fn("get_satellite_hotspots", "Titik panas satelit NASA FIRMS 24 jam terakhir di sekitar titik.",
        {"lat": _NUM, "lon": _NUM, "radius_km": _NUM}, ["lat", "lon"]),
    _fn("estimate_spread", "Perkiraan arah sebaran api dari arah angin dan desa yang terancam.",
        {"camera_id": {"type": "string"}, "wind_dir_deg": {**_NUM, "description": "arah angin BERTIUP DARI (derajat)"},
         "wind_kmh": _NUM}, ["camera_id", "wind_dir_deg", "wind_kmh"]),
    _fn("find_nearest_resources", "Posko, damkar, atau fasilitas terdekat beserta kontak (jika terverifikasi).",
        {"lat": _NUM, "lon": _NUM, "kind": {"type": "string"}}, ["lat", "lon"]),
    _fn("get_recent_events", "Ringkasan keputusan kamera ini dalam beberapa menit terakhir.",
        {"camera_id": {"type": "string"}, "minutes": {"type": "integer"}}, ["camera_id"]),
]
TOOL_NAMES = {t["function"]["name"] for t in TOOL_SCHEMAS}
