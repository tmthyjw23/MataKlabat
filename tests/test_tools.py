import pytest

from mataklabat.config import CameraConfig, Place, Resource, Resources, Settings
from mataklabat.tools import (
    IncidentTools,
    angle_diff,
    bearing_deg,
    haversine_km,
    spread_direction,
)
from tests.test_alerts import RISK

CAM = CameraConfig("CAM-01", "Kaki Dian", 0, 1.4200, 124.9800)
VILLAGES = (
    Place("Timur Dekat", 1.4200, 125.0070),  # ~3 km east
    Place("Barat Dekat", 1.4200, 124.9530),  # ~3 km west
    Place("Timur Jauh", 1.4200, 125.1600),  # ~20 km east
    Place("Timur Laut", 1.4350, 125.0000),  # ~2.8 km, bearing ~53°
)
RESOURCES = (
    Resource("Damkar Jauh", "damkar", 1.5000, 125.0500, "ISI_SENDIRI"),
    Resource("Posko Dekat", "posko", 1.4210, 124.9810, "0812-xxxx"),
)


@pytest.fixture
def tools():
    settings = Settings(root=".", cameras=(CAM,), resources=Resources(VILLAGES, RESOURCES, ()))
    return IncidentTools(settings, risk_provider=lambda: RISK)


def test_geo_helpers():
    assert haversine_km(0, 0, 1, 0) == pytest.approx(111.2, abs=0.2)
    assert bearing_deg(0, 0, 1, 0) == pytest.approx(0, abs=0.1)
    assert bearing_deg(0, 0, 0, 1) == pytest.approx(90, abs=0.1)
    assert angle_diff(350, 10) == 20 and angle_diff(10, 350) == 20


@pytest.mark.parametrize(("wind_from", "toward"), [(270, 90), (0, 180), (90, 270), (200, 20)])
def test_wind_from_pushes_fire_to_opposite_side(wind_from, toward):
    assert spread_direction(wind_from) == toward


def test_estimate_spread_west_wind_threatens_villages_to_the_east(tools):
    result = tools.estimate_spread("CAM-01", wind_dir_deg=270, wind_kmh=18)
    assert result["spread_toward_deg"] == 90 and result["spread_toward"] == "timur"
    names = [v["name"] for v in result["villages_in_path"]]
    assert names == ["Timur Laut", "Timur Dekat"]  # within ±45° of east and ≤ 8 km, nearest first
    assert result["note"] is None


def test_estimate_spread_weak_wind_note(tools):
    assert "segala arah" in tools.estimate_spread("CAM-01", 90, 2)["note"]


def test_hotspots_without_key_are_unavailable(tools):
    assert tools.get_satellite_hotspots(1.42, 124.98) == {"status": "unavailable", "reason": "FIRMS_MAP_KEY belum diisi"}


def test_hotspots_filtered_by_radius():
    csv_text = (
        "latitude,longitude,bright_ti4,confidence,acq_date,acq_time\n"
        "1.4300,124.9900,330,n,2026-10-26,0530\n"
        "1.6000,125.3000,331,h,2026-10-26,0530\n"
    )
    settings = Settings(root=".", cameras=(CAM,), resources=Resources(), firms_map_key="KEY")
    calls = []
    tools = IncidentTools(settings, lambda: None, firms_fetch=lambda *a: calls.append(a) or csv_text)
    result = tools.get_satellite_hotspots(1.42, 124.98, radius_km=10)
    assert result["status"] == "ok" and result["count"] == 1
    assert result["hotspots"][0]["distance_km"] == pytest.approx(1.6, abs=0.2)
    assert calls[0][0] == "KEY"


def test_hotspots_network_error_is_unavailable():
    settings = Settings(root=".", cameras=(CAM,), resources=Resources(), firms_map_key="KEY")

    def boom(*a):
        raise ConnectionError("offline")

    result = IncidentTools(settings, lambda: None, firms_fetch=boom).get_satellite_hotspots(1.4, 125.0)
    assert result["status"] == "unavailable" and "KEY" not in result["reason"]


def test_nearest_resources_sorted_and_unverified_contact_hidden(tools):
    result = tools.find_nearest_resources(1.42, 124.98)["resources"]
    assert [r["name"] for r in result] == ["Posko Dekat", "Damkar Jauh"]
    assert result[1]["contact"] == "belum diisi"
    assert [r["name"] for r in tools.find_nearest_resources(1.42, 124.98, "damkar")["resources"]] == ["Damkar Jauh"]


def test_weather_tool(tools):
    w = tools.get_weather(1.42, 124.98)
    assert w["wind_from"] == "barat" and w["area_risk_level"] == "Tinggi" and w["days_without_rain"] == 12
    empty = IncidentTools(tools.settings, lambda: None).get_weather(1, 2)
    assert empty["status"] == "unavailable"


def test_recent_events_summary():
    rows = [
        {"ts": "t1", "level": "AMAN", "rule": "R0"},
        {"ts": "t2", "level": "WASPADA", "rule": "R2"},
        {"ts": "t3", "level": "WASPADA", "rule": "R2"},
        {"ts": "t4", "level": "BAHAYA", "rule": "R1"},
    ]
    settings = Settings(root=".", cameras=(CAM,), resources=Resources())
    result = IncidentTools(settings, lambda: None, recent_events=lambda c, m: rows).get_recent_events("CAM-01")
    assert result["per_level"] == {"AMAN": 1, "WASPADA": 2, "BAHAYA": 1}
    assert [c["level"] for c in result["level_changes"]] == ["AMAN", "WASPADA", "BAHAYA"]


def test_call_dispatch_errors(tools):
    assert "tidak dikenal" in tools.call("rm_rf", "{}")["error"]
    assert "error" in tools.call("estimate_spread", '{"camera_id": "CAM-99", "wind_dir_deg": 1, "wind_kmh": 1}')
    assert "error" in tools.call("get_weather", "not json")
    assert tools.call("get_weather", '{"lat": 1, "lon": 2}')["area_risk_level"] == "Tinggi"
