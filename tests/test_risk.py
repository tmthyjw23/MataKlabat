from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from mataklabat.risk import RiskService, compute_risk

TZ = ZoneInfo("Asia/Makassar")
LAT, LON = 1.4667, 125.0333


def payload(start: datetime, days: int, rain_days=(), temp=31.0, rh=55.0, wind=12.0):
    """Hourly Open-Meteo-like payload; `rain_days` are day offsets with 20 mm at 06:00."""
    hourly = {k: [] for k in ("time", "temperature_2m", "relative_humidity_2m", "wind_speed_10m", "wind_direction_10m", "precipitation")}
    for h in range(days * 24):
        t = start + timedelta(hours=h)
        hourly["time"].append(t.strftime("%Y-%m-%dT%H:%M"))
        hourly["temperature_2m"].append(temp)
        hourly["relative_humidity_2m"].append(rh)
        hourly["wind_speed_10m"].append(wind)
        hourly["wind_direction_10m"].append(270.0)
        rainy = (t - start).days in rain_days and t.hour == 6
        hourly["precipitation"].append(20.0 if rainy else 0.0)
    return {"hourly": hourly}


START = datetime(2026, 7, 1, 0, 0, tzinfo=TZ)


def test_dry_spell_gives_high_risk_with_forecast():
    now = START + timedelta(days=60, hours=14)  # 30 Aug 14:00, after noon
    snap = compute_risk(payload(START, 64, rain_days=(50,)), LAT, now)
    assert snap.today.day == now.date() and snap.today.observed
    assert snap.level in ("Tinggi", "Sangat Tinggi")
    assert snap.days_without_rain == 10  # rain fell on day 50 (counted on day 50 noon)
    assert len(snap.forecast) == 3 and all(not d.observed for d in snap.forecast)
    assert snap.now_temp_c == 31.0 and snap.now_wind_dir_deg == 270.0
    assert snap.advice and snap.driver_text


def test_today_before_noon_is_marked_forecast():
    now = START + timedelta(days=60, hours=8)
    snap = compute_risk(payload(START, 64), LAT, now)
    assert snap.today.day == now.date() and not snap.today.observed


def test_wet_weather_gives_low_risk():
    rainy = tuple(range(0, 64, 2))
    snap = compute_risk(payload(START, 64, rain_days=rainy, temp=24, rh=92, wind=4), LAT, START + timedelta(days=60, hours=13))
    assert snap.level == "Rendah"


def test_rain_is_summed_over_24h_ending_at_noon():
    snap = compute_risk(payload(START, 10, rain_days=(5,)), LAT, START + timedelta(days=8, hours=13))
    by_day = {d.day: d.weather.rain_mm for d in snap.history}
    assert by_day[(START + timedelta(days=5)).date()] == 20.0  # 06:00 is before that day's noon
    assert by_day[(START + timedelta(days=6)).date()] == 0.0


def test_incomplete_payload_raises():
    with pytest.raises(ValueError):
        compute_risk(payload(START, 1), LAT, START + timedelta(hours=10))


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def test_service_keeps_last_value_and_expires_after_six_hours():
    clock = Clock(START + timedelta(days=60, hours=13))
    calls = {"n": 0}

    def fetch(lat, lon):
        calls["n"] += 1
        if calls["n"] > 1:
            raise ConnectionError("offline")
        return payload(START, 64)

    svc = RiskService(LAT, LON, fetch=fetch, clock=clock)
    assert svc.current_level() is None  # nothing fetched yet
    assert svc.refresh() is True
    level = svc.current_level()
    assert level is not None

    clock.t += timedelta(hours=2)
    assert svc.refresh() is False and "offline" in svc.last_error
    assert svc.current_level() == level  # stale but still usable
    assert svc.age_s() == pytest.approx(2 * 3600)

    clock.t += timedelta(hours=5)
    assert svc.current_level() is None  # older than 6 h: unknown
    assert svc.snapshot() is not None  # still shown on the web as old data


def test_leading_missing_days_are_skipped():
    data = payload(START, 64)
    for key in ("temperature_2m", "relative_humidity_2m", "wind_speed_10m", "wind_direction_10m", "precipitation"):
        data["hourly"][key][: 20 * 24] = [None] * (20 * 24)  # archive shorter than past_days
    snap = compute_risk(data, LAT, START + timedelta(days=60, hours=13))
    assert snap.history[0].day == (START + timedelta(days=20)).date()
    assert snap.today.day == (START + timedelta(days=60)).date()
