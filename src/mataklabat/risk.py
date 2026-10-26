"""Area fire risk from Open-Meteo weather (Spec §6).

Every refresh downloads up to 92 past days plus a short forecast and recomputes
the whole FWI chain from standard start-up values, so a restart never breaks
the drought chain and no state has to be persisted for the calculation.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo

import requests

from mataklabat import fwi
from mataklabat.config import TIMEZONE, now_local

log = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
PAST_DAYS = 92  # Open-Meteo maximum; long enough to spin up the Drought Code
FORECAST_DAYS = 4
NOON_HOUR = 12
RAIN_DAY_MM = 1.0
REFRESH_S = 3600.0
RETRY_S = 300.0
STALE_AFTER_S = 6 * 3600.0
HIGH_LEVELS = ("Tinggi", "Sangat Tinggi")

ADVICE = {
    "Rendah": "Kondisi aman. Pemantauan rutin.",
    "Sedang": "Waspadai pembakaran lahan dan sampah.",
    "Tinggi": "Larang pembakaran terbuka. Tingkatkan patroli jalur pendakian.",
    "Sangat Tinggi": "Siagakan regu pemadam. Pertimbangkan penutupan jalur pendakian.",
}

Fetcher = Callable[[float, float], dict[str, Any]]


@dataclass(frozen=True)
class DayRisk:
    day: date
    level: str
    driver: str
    indicator_levels: dict[str, str]
    codes: fwi.FwiCodes
    weather: fwi.DailyWeather
    observed: bool  # False when the day's noon lies in the future (forecast)


@dataclass(frozen=True)
class RiskSnapshot:
    fetched_at: datetime
    today: DayRisk
    forecast: tuple[DayRisk, ...]
    days_without_rain: int
    now_temp_c: float | None = None
    now_rh_pct: float | None = None
    now_wind_kmh: float | None = None
    now_wind_dir_deg: float | None = None
    history: tuple[DayRisk, ...] = field(default=(), repr=False)

    @property
    def level(self) -> str:
        return self.today.level

    @property
    def fwi(self) -> float:
        return self.today.codes.fwi

    @property
    def advice(self) -> str:
        return ADVICE[self.level]

    @property
    def driver_text(self) -> str:
        return fwi.INDICATOR_NAMES[self.today.driver]


def fetch_open_meteo(lat: float, lon: float) -> dict[str, Any]:
    resp = requests.get(
        OPEN_METEO_URL,
        params={
            "latitude": lat,
            "longitude": lon,
            "hourly": "temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m,precipitation",
            "timezone": TIMEZONE,
            "past_days": PAST_DAYS,
            "forecast_days": FORECAST_DAYS,
            "wind_speed_unit": "kmh",
        },
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def compute_risk(payload: dict[str, Any], lat: float, now: datetime) -> RiskSnapshot:
    """Turn an Open-Meteo hourly payload into today's risk, history and forecast."""
    hourly = payload["hourly"]
    tz = ZoneInfo(TIMEZONE)
    times = [datetime.fromisoformat(t).replace(tzinfo=tz) for t in hourly["time"]]
    rows = {
        t: {
            "temp": hourly["temperature_2m"][i],
            "rh": hourly["relative_humidity_2m"][i],
            "wind": hourly["wind_speed_10m"][i],
            "dir": hourly["wind_direction_10m"][i],
            "rain": hourly["precipitation"][i] or 0.0,
        }
        for i, t in enumerate(times)
    }

    # Open-Meteo returns null for the oldest part of `past_days` when the model's archive is
    # shorter, so the chain starts at the first complete day and stops at the first gap after it.
    def complete(row: dict[str, Any] | None) -> bool:
        return row is not None and all(row[k] is not None for k in ("temp", "rh", "wind"))

    days: list[tuple[date, fwi.DailyWeather, bool]] = []
    day = (times[0] + timedelta(days=1)).date()
    last_day = times[-1].date()
    while day <= last_day:
        noon = datetime(day.year, day.month, day.day, NOON_HOUR, tzinfo=tz)
        row = rows.get(noon)
        if not complete(row):
            if days:
                break
            day += timedelta(days=1)
            continue
        rain = sum(rows.get(noon - timedelta(hours=h), {}).get("rain") or 0.0 for h in range(24))
        weather = fwi.DailyWeather(row["temp"], row["rh"], row["wind"], rain, day.month)
        days.append((day, weather, noon <= now))
        day += timedelta(days=1)
    if not days:
        raise ValueError("data Open-Meteo tidak memuat satu hari pun yang lengkap")

    results: list[DayRisk] = []
    for (d, weather, observed), codes in zip(days, fwi.run([w for _, w, _ in days], lat)):
        level, driver, per = fwi.danger(codes)
        results.append(DayRisk(d, level, driver, per, codes, weather, observed))

    today_date = now.date()
    past = [r for r in results if r.day <= today_date]
    today = past[-1] if past else results[0]
    forecast = tuple(r for r in results if r.day > today.day)[: FORECAST_DAYS - 1]

    dry_days = 0
    for r in reversed(past):
        if r.weather.rain_mm >= RAIN_DAY_MM:
            break
        dry_days += 1

    current_hour = now.replace(minute=0, second=0, microsecond=0)
    current = rows.get(current_hour, {})
    return RiskSnapshot(
        fetched_at=now,
        today=today,
        forecast=forecast,
        days_without_rain=dry_days,
        now_temp_c=current.get("temp"),
        now_rh_pct=current.get("rh"),
        now_wind_kmh=current.get("wind"),
        now_wind_dir_deg=current.get("dir"),
        history=tuple(past),
    )


class RiskService:
    """Keeps an up-to-date RiskSnapshot, refreshed hourly in a background thread."""

    def __init__(
        self,
        lat: float,
        lon: float,
        fetch: Fetcher = fetch_open_meteo,
        clock: Callable[[], datetime] = now_local,
        refresh_s: float = REFRESH_S,
        retry_s: float = RETRY_S,
        stale_after_s: float = STALE_AFTER_S,
    ):
        self.lat, self.lon = lat, lon
        self._fetch = fetch
        self._clock = clock
        self.refresh_s = refresh_s
        self.retry_s = retry_s
        self.stale_after_s = stale_after_s
        self._lock = threading.Lock()
        self._snapshot: RiskSnapshot | None = None
        self.last_error: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def refresh(self) -> bool:
        try:
            snapshot = compute_risk(self._fetch(self.lat, self.lon), self.lat, self._clock())
        except Exception as exc:  # noqa: BLE001 - network/data errors keep the last value
            self.last_error = f"{type(exc).__name__}: {exc}"[:200]
            log.warning("Gagal memperbarui risiko kawasan: %s", self.last_error)
            return False
        with self._lock:
            self._snapshot = snapshot
        self.last_error = None
        log.info(
            "Risiko kawasan: %s (karena %s), FWI %.1f, %d hari tanpa hujan.",
            snapshot.level, snapshot.driver_text, snapshot.fwi, snapshot.days_without_rain,
        )
        return True

    def snapshot(self) -> RiskSnapshot | None:
        with self._lock:
            return self._snapshot

    def age_s(self) -> float | None:
        snap = self.snapshot()
        return None if snap is None else (self._clock() - snap.fetched_at).total_seconds()

    def current(self) -> RiskSnapshot | None:
        """The snapshot if it is fresh enough to act on, else None ("tidak diketahui")."""
        age = self.age_s()
        if age is None or age > self.stale_after_s:
            return None
        return self.snapshot()

    def current_level(self) -> str | None:
        snap = self.current()
        return None if snap is None else snap.level

    def start(self) -> RiskService:
        if self._thread is None or not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="risk", daemon=True)
            self._thread.start()
        return self

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)

    def _run(self) -> None:
        while not self._stop.is_set():
            ok = self.refresh()
            self._stop.wait(self.refresh_s if ok else self.retry_s)
