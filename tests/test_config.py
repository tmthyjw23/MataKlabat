import logging
import os
import subprocess
import sys
from dataclasses import fields
from pathlib import Path

import pytest

from mataklabat.__main__ import main
from mataklabat.config import PROJECT_ROOT, ConfigError, Settings, load_settings

VALID_CAMERAS = """
cameras:
  - {id: CAM-01, name: "Webcam", source: 0, lat: 1.42, lon: 124.98, facing_deg: 60}
  - {id: CAM-02, name: "Video", source: "data/videos/cam02.mp4", lat: 1.44, lon: 125.0}
"""

VALID_RESOURCES = """
villages:
  - {name: "Airmadidi", lat: 1.4196, lon: 124.9822}
resources:
  - {name: "Posko", kind: posko, lat: 1.419, lon: 124.983, contact: "ISI_SENDIRI"}
reference_points:
  - {name: "Puncak Klabat", lat: 1.4667, lon: 125.0333}
"""

ENV_NAMES = [
    "LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL", "PROMPT_VERSION", "AUTO_SEND_ALERT",
    "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "FIRMS_MAP_KEY", "YOLO_WEIGHTS",
] + [f.name.upper() for f in fields(Settings)]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def make_root(tmp_path: Path, cameras: str = VALID_CAMERAS, resources: str | None = VALID_RESOURCES) -> Path:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "cameras.yaml").write_text(cameras, encoding="utf-8")
    if resources is not None:
        (tmp_path / "config" / "resources.yaml").write_text(resources, encoding="utf-8")
    return tmp_path


def test_repo_config_loads():
    s = load_settings(PROJECT_ROOT, env_file=None)
    assert [c.id for c in s.cameras] == ["CAM-01", "CAM-02", "CAM-03", "CAM-04"]
    assert s.cameras[0].source == 0
    assert len(s.resources.villages) == 5
    assert s.resources.reference_points[0].name == "Puncak Klabat"


def test_defaults_match_architecture(tmp_path):
    s = load_settings(make_root(tmp_path))
    assert (s.conf_danger, s.conf_danger_high_risk, s.conf_warn) == (0.70, 0.60, 0.40)
    assert (s.confirm_window, s.confirm_min, s.clear_steps) == (3, 2, 4)
    assert (s.fire_trigger, s.smoke_trigger, s.recheck_s) == (0.15, 0.20, 15.0)
    assert s.agent_cooldown_s == 600
    assert s.prompt_version == "v2"
    assert s.timezone == "Asia/Makassar"


def test_relative_video_source_resolved_against_root(tmp_path):
    s = load_settings(make_root(tmp_path))
    assert s.cameras[1].source == str(tmp_path / "data/videos/cam02.mp4")


def test_missing_llm_model_disables_llm(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        s = load_settings(make_root(tmp_path))
    assert s.llm_enabled is False
    assert s.llm_model is None
    assert s.llm_base_url == "http://localhost:20128/v1"
    assert "LLM_MODEL" in caplog.text


def test_placeholder_values_count_as_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "isi_nama_model_dari_9router")
    monkeypatch.setenv("LLM_API_KEY", "isi_api_key_dari_dashboard_9router")
    s = load_settings(make_root(tmp_path))
    assert s.llm_enabled is False and s.llm_api_key is None


def test_llm_settings_and_key_stays_out_of_repr(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "gc/gemini-2.5-flash")
    monkeypatch.setenv("LLM_API_KEY", "secret-123")
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:9999/v1/")
    s = load_settings(make_root(tmp_path))
    assert s.llm_enabled is True
    assert s.llm_model == "gc/gemini-2.5-flash"
    assert s.llm_base_url == "http://127.0.0.1:9999/v1"
    assert "secret-123" not in repr(s)


def test_dotenv_file_is_read(tmp_path):
    root = make_root(tmp_path)
    (root / ".env").write_text("LLM_MODEL=from-dotenv\nCONF_DANGER=0.75\n", encoding="utf-8")
    try:
        s = load_settings(root)
        assert s.llm_model == "from-dotenv"
        assert s.conf_danger == 0.75
    finally:
        os.environ.pop("LLM_MODEL", None)
        os.environ.pop("CONF_DANGER", None)


def test_env_overrides_constants(tmp_path, monkeypatch):
    monkeypatch.setenv("CONF_DANGER", "0.8")
    monkeypatch.setenv("CONFIRM_WINDOW", "5")
    monkeypatch.setenv("AUTO_SEND_ALERT", "true")
    s = load_settings(make_root(tmp_path))
    assert s.conf_danger == 0.8
    assert s.confirm_window == 5 and isinstance(s.confirm_window, int)
    assert s.auto_send_alert is True


@pytest.mark.parametrize(
    ("name", "value", "fragment"),
    [
        ("CONF_DANGER", "tinggi", "CONF_DANGER"),
        ("CONFIRM_WINDOW", "2.5", "CONFIRM_WINDOW"),
        ("CONF_WARN", "1.5", "CONF_WARN"),
        ("CONFIRM_MIN", "9", "CONFIRM_MIN"),
        ("PROMPT_VERSION", "v9", "PROMPT_VERSION"),
    ],
)
def test_invalid_env_values_fail_clearly(tmp_path, monkeypatch, name, value, fragment):
    monkeypatch.setenv(name, value)
    with pytest.raises(ConfigError, match=fragment):
        load_settings(make_root(tmp_path))


@pytest.mark.parametrize(
    ("cameras", "fragment"),
    [
        ("cameras: []", "tidak kosong"),
        ("foo: bar", "tidak kosong"),
        ("cameras:\n  - {id: CAM-01, name: A, source: 0, lon: 125.0}", "lat"),
        ("cameras:\n  - {id: CAM-01, name: A, source: 0, lat: utara, lon: 125.0}", "angka"),
        ("cameras:\n  - {id: CAM-01, name: A, source: 0, lat: 120, lon: 125.0}", "rentang"),
        (
            "cameras:\n  - {id: X, name: A, source: 0, lat: 1, lon: 2}\n  - {id: X, name: B, source: 1, lat: 1, lon: 2}",
            "lebih dari sekali",
        ),
        ("cameras:\n  - {id: CAM-01, name: A, source: [1], lat: 1, lon: 2}", "source"),
        ("cameras: [unclosed", "YAML tidak valid"),
    ],
)
def test_invalid_cameras_yaml_fails_clearly(tmp_path, cameras, fragment):
    with pytest.raises(ConfigError, match=fragment) as exc:
        load_settings(make_root(tmp_path, cameras=cameras))
    assert "cameras.yaml" in str(exc.value)


def test_missing_cameras_file_fails_clearly(tmp_path):
    with pytest.raises(ConfigError, match="tidak ditemukan"):
        load_settings(tmp_path)


def test_missing_resources_file_is_tolerated(tmp_path):
    s = load_settings(make_root(tmp_path, resources=None))
    assert s.resources.villages == ()


def test_unknown_camera_id(tmp_path):
    s = load_settings(make_root(tmp_path))
    with pytest.raises(ConfigError, match="CAM-99"):
        s.camera("CAM-99")


def test_help_lists_commands(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "run" in out and "check" in out


def test_module_entry_point_help():
    env = {**os.environ, "PYTHONPATH": str(PROJECT_ROOT / "src")}
    result = subprocess.run(
        [sys.executable, "-m", "mataklabat", "--help"],
        capture_output=True, text=True, encoding="utf-8", env=env, cwd=PROJECT_ROOT, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "run" in result.stdout and "check" in result.stdout


def test_photo_camera_mode(tmp_path):
    cams = VALID_CAMERAS + '  - {id: CAM-03, name: "Foto", source: "data/demo/CAM-03", lat: 1.4, lon: 125.0, mode: foto}\n'
    s = load_settings(make_root(tmp_path, cameras=cams))
    cam = s.camera("CAM-03")
    assert cam.is_photo and cam.source == str(tmp_path / "data/demo/CAM-03")
    assert not s.camera("CAM-01").is_photo


@pytest.mark.parametrize(
    ("line", "fragment"),
    [
        ('{id: X, name: A, source: "d", lat: 1, lon: 2, mode: slideshow}', "mode"),
        ("{id: X, name: A, source: 0, lat: 1, lon: 2, mode: foto}", "folder"),
    ],
)
def test_invalid_photo_mode(tmp_path, line, fragment):
    with pytest.raises(ConfigError, match=fragment):
        load_settings(make_root(tmp_path, cameras=f"cameras:\n  - {line}\n"))


def test_risk_point_prefers_reference_point(tmp_path):
    assert load_settings(make_root(tmp_path)).risk_point == (1.4667, 125.0333)


def test_risk_point_falls_back_to_first_camera(tmp_path):
    assert load_settings(make_root(tmp_path, resources=None)).risk_point == (1.42, 124.98)


def test_weather_point_wins_over_reference_point(tmp_path):
    res = VALID_RESOURCES + 'weather_point: {name: "Kaki", lat: 1.43, lon: 124.98}\n'
    assert load_settings(make_root(tmp_path, resources=res)).risk_point == (1.43, 124.98)


def test_repo_weather_point_is_on_the_lower_slope():
    s = load_settings(PROJECT_ROOT, env_file=None)
    assert s.risk_point == (1.42749, 124.98029)
