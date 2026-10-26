import pytest

from mataklabat import fwi as F

# Van Wagner & Pickett (1985), Forestry Technical Report 33, sample run (April, ~46°N).
# Columns: temp, rh, wind, rain -> ffmc, dmc, dc, isi, bui, fwi (None = not asserted).
REFERENCE = [
    ((17.0, 42, 25, 0.0), (87.7, 8.5, 19.0, 10.9, 8.5, 10.1)),
    ((20.0, 21, 25, 2.4), (86.2, 10.4, 23.6, 8.8, 10.4, None)),
    ((8.5, 40, 17, 0.0), (87.0, 11.8, 26.1, 6.5, 11.7, 7.6)),
    ((6.5, 25, 6, 0.0), (88.8, 13.2, 28.2, 4.9, 13.1, 6.2)),
    ((13.0, 34, 24, 0.0), (89.1, 15.4, 31.5, 12.6, 15.3, 14.8)),
]


def test_matches_reference_run():
    days = [F.DailyWeather(t, h, w, r, 4) for (t, h, w, r), _ in REFERENCE]
    for codes, (_, expected) in zip(F.run(days, lat=46.0), REFERENCE):
        got = (codes.ffmc, codes.dmc, codes.dc, codes.isi, codes.bui, codes.fwi)
        for value, want in zip(got, expected):
            if want is not None:
                assert value == pytest.approx(want, abs=0.1)


def test_equatorial_day_length_factors():
    # Near the equator DMC uses day length 9.0 and DC uses factor 1.4 in every month.
    jan = F.dmc(10, 30, 50, 0, month=1, lat=1.47)
    jul = F.dmc(10, 30, 50, 0, month=7, lat=1.47)
    assert jan == pytest.approx(jul)
    assert jan == pytest.approx(10 + 1.894 * 31.1 * 50 * 9.0 * 1e-4)
    assert F.dc(100, 30, 0, month=1, lat=1.47) == pytest.approx(100 + (0.36 * 32.8 + 1.4) / 2)


def test_rain_lowers_codes():
    dry = F.step(None, F.DailyWeather(32, 45, 10, 0.0, 9), lat=1.47)
    wet = F.step(dry, F.DailyWeather(25, 90, 5, 30.0, 9), lat=1.47)
    assert wet.ffmc < dry.ffmc and wet.dmc < dry.dmc + 1 and wet.dc < dry.dc


def test_long_drought_raises_dc():
    codes = F.run([F.DailyWeather(32, 50, 10, 0.0, 9)] * 60, lat=1.47)
    assert codes[-1].dc > codes[0].dc + 300


@pytest.mark.parametrize(
    ("value", "cls"), [(0, 0), (72.4, 0), (72.6, 1), (77, 1), (78, 2), (82.4, 2), (83, 3), (99, 3)]
)
def test_ffmc_classes(value, cls):
    assert F.ffmc_class(value) == cls


@pytest.mark.parametrize(("value", "cls"), [(0, 0), (139.9, 0), (140, 1), (259, 1), (260, 2), (350, 2), (351, 3)])
def test_dc_classes(value, cls):
    assert F.dc_class(value) == cls


@pytest.mark.parametrize(("value", "cls"), [(0, 0), (1.4, 0), (1.6, 1), (3, 1), (4, 2), (5.4, 2), (6, 3)])
def test_isi_classes(value, cls):
    assert F.isi_class(value) == cls


def test_danger_is_highest_class_with_driver():
    codes = F.FwiCodes(ffmc=80, dmc=20, dc=100, isi=1, bui=20, fwi=5)
    level, driver, per = F.danger(codes)
    assert (level, driver) == ("Tinggi", "ffmc")
    assert per == {"ffmc": "Tinggi", "dc": "Rendah", "isi": "Rendah"}
