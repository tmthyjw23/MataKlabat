"""Canadian Forest Fire Weather Index (FWI) System, pure functions.

Equations: Van Wagner (1987) "Development and structure of the Canadian Forest
Fire Weather Index System", and Van Wagner & Pickett (1985), Forestry Technical
Report 33. Latitude adjustments follow the `cffdrs` R package: near the equator
the DMC day-length factor is 9.0 (|lat| <= 10) and the DC factor is 1.4
(|lat| <= 20).

Danger classes follow the Indonesian Fire Danger Rating System:
de Groot et al. (2006), Mitig Adapt Strat Glob Change 12:165-180, Tables 1-3.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

FFMC_START = 85.0
DMC_START = 6.0
DC_START = 15.0

# Effective day length for DMC (Van Wagner 1987, Table 1, ~46°N).
_DMC_DAY_LENGTH_46N = (6.5, 7.5, 9.0, 12.8, 13.9, 13.9, 12.4, 10.9, 9.4, 8.0, 7.0, 6.0)
_DMC_DAY_LENGTH_EQUATOR = 9.0
# Day-length factor for DC (Van Wagner 1987, Table 2), north and south of 20°.
_DC_FACTOR_NORTH = (-1.6, -1.6, -1.6, 0.9, 3.8, 5.8, 6.4, 5.0, 2.4, 0.4, -1.6, -1.6)
_DC_FACTOR_SOUTH = (6.4, 5.0, 2.4, 0.4, -1.6, -1.6, -1.6, -1.6, -1.6, 0.9, 3.8, 5.8)
_DC_FACTOR_EQUATOR = 1.4

LEVELS = ("Rendah", "Sedang", "Tinggi", "Sangat Tinggi")


@dataclass(frozen=True)
class DailyWeather:
    """Noon (local standard time) observations plus 24 h rain ending at noon."""

    temp_c: float
    rh_pct: float
    wind_kmh: float
    rain_mm: float
    month: int


@dataclass(frozen=True)
class FwiCodes:
    ffmc: float
    dmc: float
    dc: float
    isi: float
    bui: float
    fwi: float


def ffmc(prev: float, temp: float, rh: float, wind: float, rain: float) -> float:
    rh = min(100.0, max(0.0, rh))
    mo = 147.2 * (101.0 - prev) / (59.5 + prev)
    if rain > 0.5:
        rf = rain - 0.5
        wetting = 42.5 * rf * math.exp(-100.0 / (251.0 - mo)) * (1.0 - math.exp(-6.93 / rf))
        if mo > 150.0:
            mo += wetting + 0.0015 * (mo - 150.0) ** 2 * math.sqrt(rf)
        else:
            mo += wetting
        mo = min(mo, 250.0)
    ed = 0.942 * rh**0.679 + 11.0 * math.exp((rh - 100.0) / 10.0) + 0.18 * (21.1 - temp) * (
        1.0 - math.exp(-0.115 * rh)
    )
    if mo > ed:
        ko = 0.424 * (1.0 - (rh / 100.0) ** 1.7) + 0.0694 * math.sqrt(wind) * (1.0 - (rh / 100.0) ** 8)
        kd = ko * 0.581 * math.exp(0.0365 * temp)
        m = ed + (mo - ed) * 10.0 ** (-kd)
    else:
        ew = 0.618 * rh**0.753 + 10.0 * math.exp((rh - 100.0) / 10.0) + 0.18 * (21.1 - temp) * (
            1.0 - math.exp(-0.115 * rh)
        )
        if mo < ew:
            dry = (100.0 - rh) / 100.0
            k1 = 0.424 * (1.0 - dry**1.7) + 0.0694 * math.sqrt(wind) * (1.0 - dry**8)
            kw = k1 * 0.581 * math.exp(0.0365 * temp)
            m = ew - (ew - mo) * 10.0 ** (-kw)
        else:
            m = mo
    return min(101.0, max(0.0, 59.5 * (250.0 - m) / (147.2 + m)))


def dmc(prev: float, temp: float, rh: float, rain: float, month: int, lat: float) -> float:
    temp = max(temp, -1.1)
    day_length = _DMC_DAY_LENGTH_EQUATOR if -10.0 < lat <= 10.0 else _DMC_DAY_LENGTH_46N[month - 1]
    rk = 1.894 * (temp + 1.1) * (100.0 - rh) * day_length * 1e-4
    if rain > 1.5:
        re = 0.92 * rain - 1.27
        mo = 20.0 + 280.0 / math.exp(0.023 * prev)
        if prev <= 33.0:
            b = 100.0 / (0.5 + 0.3 * prev)
        elif prev <= 65.0:
            b = 14.0 - 1.3 * math.log(prev)
        else:
            b = 6.2 * math.log(prev) - 17.2
        mr = mo + 1000.0 * re / (48.77 + b * re)
        pr = max(0.0, 244.72 - 43.43 * math.log(mr - 20.0))
    else:
        pr = prev
    return max(0.0, pr + rk)


def dc(prev: float, temp: float, rain: float, month: int, lat: float) -> float:
    temp = max(temp, -2.8)
    if lat > 20.0:
        factor = _DC_FACTOR_NORTH[month - 1]
    elif lat <= -20.0:
        factor = _DC_FACTOR_SOUTH[month - 1]
    else:
        factor = _DC_FACTOR_EQUATOR
    pe = max(0.0, (0.36 * (temp + 2.8) + factor) / 2.0)
    if rain > 2.8:
        rw = 0.83 * rain - 1.27
        smi = 800.0 * math.exp(-prev / 400.0)
        dr = max(0.0, prev - 400.0 * math.log(1.0 + 3.937 * rw / smi))
    else:
        dr = prev
    return max(0.0, dr + pe)


def isi(ffmc_value: float, wind: float) -> float:
    fm = 147.2 * (101.0 - ffmc_value) / (59.5 + ffmc_value)
    fine_fuel = 91.9 * math.exp(-0.1386 * fm) * (1.0 + fm**5.31 / 4.93e7)
    return 0.208 * fine_fuel * math.exp(0.05039 * wind)


def bui(dmc_value: float, dc_value: float) -> float:
    if dmc_value == 0.0 and dc_value == 0.0:
        return 0.0
    if dmc_value <= 0.4 * dc_value:
        value = 0.8 * dmc_value * dc_value / (dmc_value + 0.4 * dc_value)
    else:
        value = dmc_value - (1.0 - 0.8 * dc_value / (dmc_value + 0.4 * dc_value)) * (
            0.92 + (0.0114 * dmc_value) ** 1.7
        )
    return max(0.0, value)


def fwi(isi_value: float, bui_value: float) -> float:
    if bui_value <= 80.0:
        bb = 0.1 * isi_value * (0.626 * bui_value**0.809 + 2.0)
    else:
        bb = 0.1 * isi_value * (1000.0 / (25.0 + 108.64 * math.exp(-0.023 * bui_value)))
    if bb <= 1.0:
        return bb
    return math.exp(2.72 * (0.434 * math.log(bb)) ** 0.647)


def step(prev: FwiCodes | None, w: DailyWeather, lat: float) -> FwiCodes:
    """Advance the moisture codes by one day."""
    p_ffmc, p_dmc, p_dc = (FFMC_START, DMC_START, DC_START) if prev is None else (prev.ffmc, prev.dmc, prev.dc)
    f = ffmc(p_ffmc, w.temp_c, w.rh_pct, w.wind_kmh, w.rain_mm)
    d = dmc(p_dmc, w.temp_c, w.rh_pct, w.rain_mm, w.month, lat)
    c = dc(p_dc, w.temp_c, w.rain_mm, w.month, lat)
    i = isi(f, w.wind_kmh)
    b = bui(d, c)
    return FwiCodes(ffmc=f, dmc=d, dc=c, isi=i, bui=b, fwi=fwi(i, b))


def run(days: list[DailyWeather], lat: float, start: FwiCodes | None = None) -> list[FwiCodes]:
    """Compute the codes for consecutive days, starting from standard start-up values."""
    out: list[FwiCodes] = []
    prev = start
    for w in days:
        prev = step(prev, w, lat)
        out.append(prev)
    return out


# --- Indonesian FDRS danger classes (de Groot et al. 2006) -------------------------


def ffmc_class(value: float) -> int:
    """Ignition potential (Table 2): 0-72, 73-77, 78-82, 83+."""
    v = round(value)
    return 0 if v <= 72 else 1 if v <= 77 else 2 if v <= 82 else 3


def dc_class(value: float) -> int:
    """Smoke/drought potential (Table 1): <140, 140-260, 260-350, >350."""
    return 0 if value < 140 else 1 if value < 260 else 2 if value <= 350 else 3


def isi_class(value: float) -> int:
    """Difficulty of control in grasslands (Table 3): 0-1, 2-3, 4-5, 6+."""
    v = round(value)
    return 0 if v <= 1 else 1 if v <= 3 else 2 if v <= 5 else 3


INDICATOR_NAMES = {
    "ffmc": "potensi penyalaan",
    "dc": "kekeringan",
    "isi": "sulitnya pemadaman",
}


def danger(codes: FwiCodes) -> tuple[str, str, dict[str, str]]:
    """Area risk = highest of the three FDRS classes.

    Returns (level, driving indicator key, level per indicator).
    """
    classes = {"ffmc": ffmc_class(codes.ffmc), "dc": dc_class(codes.dc), "isi": isi_class(codes.isi)}
    driver = max(classes, key=lambda k: classes[k])
    return LEVELS[classes[driver]], driver, {k: LEVELS[v] for k, v in classes.items()}
