"""Load `.env`, `config/cameras.yaml` and `config/resources.yaml` into `Settings`.

Every numeric constant (ARCHITECTURE §4 and §6.2) can be overridden through an
environment variable with the same name in upper case, e.g. `CONF_DANGER=0.8`.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field, fields
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml
from dotenv import load_dotenv

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LLM_BASE_URL = "http://localhost:20128/v1"  # 9router, OpenAI-compatible
TIMEZONE = "Asia/Makassar"
PROMPT_VERSIONS = ("v1", "v2")

_PLACEHOLDER_PREFIX = "isi_"  # values copied unchanged from .env.example
_TRUE_VALUES = {"1", "true", "yes", "ya", "on"}


def now_local() -> datetime:
    """Current time as an aware datetime in the display timezone (Asia/Makassar)."""
    return datetime.now(ZoneInfo(TIMEZONE))


class ConfigError(ValueError):
    """Invalid configuration. The message is shown to the user as-is."""


@dataclass(frozen=True)
class CameraConfig:
    id: str
    name: str
    source: int | str  # webcam index, video path, or stream URL
    lat: float
    lon: float
    facing_deg: float = 0.0


@dataclass(frozen=True)
class Place:
    name: str
    lat: float
    lon: float


@dataclass(frozen=True)
class Resource:
    name: str
    kind: str
    lat: float
    lon: float
    contact: str = "ISI_SENDIRI"


@dataclass(frozen=True)
class Resources:
    villages: tuple[Place, ...] = ()
    resources: tuple[Resource, ...] = ()
    reference_points: tuple[Place, ...] = ()


@dataclass(frozen=True, kw_only=True)
class Settings:
    root: Path
    cameras: tuple[CameraConfig, ...]
    resources: Resources

    # LLM (any OpenAI-compatible endpoint; 9router by default)
    llm_base_url: str = DEFAULT_LLM_BASE_URL
    llm_api_key: str | None = field(default=None, repr=False)
    llm_model: str | None = None
    llm_enabled: bool = False
    prompt_version: str = "v2"

    # Notifications and optional integrations
    telegram_bot_token: str | None = field(default=None, repr=False)
    telegram_chat_id: str | None = None
    auto_send_alert: bool = False
    firms_map_key: str | None = field(default=None, repr=False)
    yolo_weights: Path | None = None
    timezone: str = TIMEZONE

    # Pipeline pacing
    process_fps: float = 2.0
    llm_min_interval_s: float = 8.0
    heartbeat_s: float = 120.0

    # §4.1 local detector
    fire_gain: float = 25.0
    smoke_gain: float = 8.0

    # §4.3 triggers to stage 2
    fire_trigger: float = 0.15
    smoke_trigger: float = 0.20
    trigger_window: int = 5
    trigger_min_hits: int = 3
    recheck_s: float = 15.0

    # §6.2 decision thresholds
    conf_danger: float = 0.70
    conf_danger_high_risk: float = 0.60
    conf_warn: float = 0.40
    conf_single_confirm: float = 0.90
    confirm_window: int = 3
    confirm_min: int = 2
    clear_steps: int = 4
    agent_cooldown_s: float = 600.0
    fri_high: int = 60

    @property
    def runtime_dir(self) -> Path:
        return self.root / "data" / "runtime"

    @property
    def db_path(self) -> Path:
        return self.runtime_dir / "events.db"

    @property
    def snapshot_dir(self) -> Path:
        return self.runtime_dir / "snapshots"

    def camera(self, camera_id: str) -> CameraConfig:
        for cam in self.cameras:
            if cam.id == camera_id:
                return cam
        known = ", ".join(c.id for c in self.cameras)
        raise ConfigError(f"Kamera '{camera_id}' tidak ada di cameras.yaml. Pilihan: {known}.")


def load_settings(
    root: Path | str | None = None,
    env_file: Path | str | None = ".env",
) -> Settings:
    """Build `Settings` from files under `root`. Pass `env_file=None` to skip `.env`."""
    root = Path(root) if root is not None else PROJECT_ROOT
    if env_file is not None:
        env_path = root / env_file
        if env_path.is_file():
            load_dotenv(env_path, override=False)

    cameras = _load_cameras(root / "config" / "cameras.yaml", root)
    resources = _load_resources(root / "config" / "resources.yaml")

    llm_model = _env_str("LLM_MODEL")
    if llm_model is None:
        log.warning(
            "LLM_MODEL kosong: verifikasi LLM dan AI Agent dimatikan, "
            "sistem hanya memakai detektor lokal."
        )

    prompt_version = _env_str("PROMPT_VERSION") or "v2"
    if prompt_version not in PROMPT_VERSIONS:
        raise ConfigError(
            f"PROMPT_VERSION={prompt_version!r} tidak dikenal. Pilihan: {', '.join(PROMPT_VERSIONS)}."
        )

    yolo = _env_str("YOLO_WEIGHTS")
    settings = Settings(
        root=root,
        cameras=cameras,
        resources=resources,
        llm_base_url=(_env_str("LLM_BASE_URL") or DEFAULT_LLM_BASE_URL).rstrip("/"),
        llm_api_key=_env_str("LLM_API_KEY"),
        llm_model=llm_model,
        llm_enabled=llm_model is not None,
        prompt_version=prompt_version,
        telegram_bot_token=_env_str("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=_env_str("TELEGRAM_CHAT_ID"),
        auto_send_alert=(_env_str("AUTO_SEND_ALERT") or "false").lower() in _TRUE_VALUES,
        firms_map_key=_env_str("FIRMS_MAP_KEY"),
        yolo_weights=Path(yolo) if yolo else None,
        **_numeric_overrides(),
    )
    _validate(settings)
    return settings


def _env_str(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    if not value or value.lower().startswith(_PLACEHOLDER_PREFIX):
        return None
    return value


def _numeric_overrides() -> dict[str, int | float]:
    overrides: dict[str, int | float] = {}
    for f in fields(Settings):
        default = f.default
        if isinstance(default, bool) or not isinstance(default, (int, float)):
            continue
        raw = os.getenv(f.name.upper(), "").strip()
        if not raw:
            continue
        kind = type(default)
        try:
            overrides[f.name] = kind(raw)
        except ValueError:
            jenis = "bilangan bulat" if kind is int else "angka"
            raise ConfigError(f"{f.name.upper()}={raw!r} harus berupa {jenis}.") from None
    return overrides


def _validate(s: Settings) -> None:
    problems = []
    if s.process_fps <= 0:
        problems.append("PROCESS_FPS harus > 0")
    for name in ("llm_min_interval_s", "heartbeat_s", "recheck_s", "agent_cooldown_s"):
        if getattr(s, name) < 0:
            problems.append(f"{name.upper()} tidak boleh negatif")
    for name in (
        "fire_trigger", "smoke_trigger", "conf_danger",
        "conf_danger_high_risk", "conf_warn", "conf_single_confirm",
    ):
        if not 0.0 <= getattr(s, name) <= 1.0:
            problems.append(f"{name.upper()} harus di antara 0 dan 1")
    if not 1 <= s.trigger_min_hits <= s.trigger_window:
        problems.append("TRIGGER_MIN_HITS harus di antara 1 dan TRIGGER_WINDOW")
    if not 1 <= s.confirm_min <= s.confirm_window:
        problems.append("CONFIRM_MIN harus di antara 1 dan CONFIRM_WINDOW")
    if s.clear_steps < 1:
        problems.append("CLEAR_STEPS minimal 1")
    if problems:
        raise ConfigError("Konstanta tidak valid: " + "; ".join(problems) + ".")


def _read_yaml(path: Path) -> Any:
    if not path.is_file():
        raise ConfigError(f"File konfigurasi tidak ditemukan: {path}")
    try:
        with path.open(encoding="utf-8") as fh:
            return yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path.name}: YAML tidak valid ({exc}).") from None


def _number(item: dict, key: str, where: str, lo: float, hi: float) -> float:
    value = item.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{where}: '{key}' harus berupa angka, bukan {value!r}.")
    if not lo <= value <= hi:
        raise ConfigError(f"{where}: '{key}'={value} di luar rentang {lo}..{hi}.")
    return float(value)


def _parse_source(raw: Any, root: Path, where: str) -> int | str:
    if isinstance(raw, bool) or not isinstance(raw, (int, str)) or raw == "":
        raise ConfigError(f"{where}: 'source' harus indeks webcam, path video, atau URL.")
    if isinstance(raw, int):
        return raw
    if raw.isdigit():
        return int(raw)
    if "://" in raw or Path(raw).is_absolute():
        return raw
    return str(root / raw)


def _load_cameras(path: Path, root: Path) -> tuple[CameraConfig, ...]:
    data = _read_yaml(path)
    items = data.get("cameras") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        raise ConfigError(f"{path.name}: harus berisi daftar 'cameras' yang tidak kosong.")

    cameras: list[CameraConfig] = []
    seen: set[str] = set()
    for i, item in enumerate(items, start=1):
        where = f"{path.name} kamera ke-{i}"
        if not isinstance(item, dict):
            raise ConfigError(f"{where}: harus berupa mapping (id, name, source, lat, lon).")
        missing = [k for k in ("id", "name", "source", "lat", "lon") if k not in item]
        if missing:
            raise ConfigError(f"{where}: field wajib tidak ada: {', '.join(missing)}.")
        cam_id = str(item["id"]).strip()
        if not cam_id:
            raise ConfigError(f"{where}: 'id' tidak boleh kosong.")
        if cam_id in seen:
            raise ConfigError(f"{path.name}: id kamera '{cam_id}' dipakai lebih dari sekali.")
        seen.add(cam_id)
        where = f"{path.name} kamera {cam_id}"
        facing = item.get("facing_deg", 0.0)
        cameras.append(
            CameraConfig(
                id=cam_id,
                name=str(item["name"]),
                source=_parse_source(item["source"], root, where),
                lat=_number(item, "lat", where, -90, 90),
                lon=_number(item, "lon", where, -180, 180),
                facing_deg=_number({"facing_deg": facing}, "facing_deg", where, 0, 360) % 360,
            )
        )
    return tuple(cameras)


def _load_resources(path: Path) -> Resources:
    if not path.is_file():
        log.warning("%s tidak ditemukan: agent tidak punya data desa dan sumber daya.", path)
        return Resources()
    data = _read_yaml(path) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path.name}: isi file harus berupa mapping.")

    def entries(key: str) -> list[dict]:
        items = data.get(key) or []
        if not isinstance(items, list) or not all(isinstance(x, dict) for x in items):
            raise ConfigError(f"{path.name}: '{key}' harus berupa daftar mapping.")
        return items

    def place(item: dict, where: str) -> Place:
        if not item.get("name"):
            raise ConfigError(f"{where}: 'name' wajib diisi.")
        return Place(
            name=str(item["name"]),
            lat=_number(item, "lat", where, -90, 90),
            lon=_number(item, "lon", where, -180, 180),
        )

    villages = tuple(place(x, f"{path.name} villages") for x in entries("villages"))
    refs = tuple(place(x, f"{path.name} reference_points") for x in entries("reference_points"))
    resources = []
    for item in entries("resources"):
        where = f"{path.name} resources"
        p = place(item, where)
        if not item.get("kind"):
            raise ConfigError(f"{where} '{p.name}': 'kind' wajib diisi.")
        resources.append(
            Resource(
                name=p.name,
                kind=str(item["kind"]),
                lat=p.lat,
                lon=p.lon,
                contact=str(item.get("contact") or "ISI_SENDIRI"),
            )
        )
    return Resources(villages=villages, resources=tuple(resources), reference_points=refs)
