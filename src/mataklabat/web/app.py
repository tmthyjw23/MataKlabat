"""FastAPI app: JSON API, live updates over SSE, and the static pages.

Viewers only read. A logged-in operator can switch cameras on or off and pick a
demo photo for a photo camera; those choices go to control.db (never events.db,
which only the monitor writes). Photos are served by camera id, event id or exact
gallery file name, never by a path taken from the request.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import secrets
import time
from urllib.parse import urlsplit
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from mataklabat.config import Settings, now_local
from mataklabat.control import CameraControl, gallery_photo, gallery_photos, show_photo, shown_photo, thumbnail
from mataklabat.decision import Level
from mataklabat.storage import ReadStore, iso
from mataklabat.tools import IncidentTools

STATIC_DIR = Path(__file__).parent / "static"
MONITOR_STALE_S = 15.0
SSE_POLL_S = 1.0
SSE_KEEPALIVE_S = 15.0
HOTSPOT_CACHE_S = 1800.0

TILE_HOSTS = (
    "https://*.tile.opentopomap.org",
    "https://tile.openstreetmap.org",
    "https://tiles.maps.eox.at",
)
CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self'",
    "img-src 'self' data: " + " ".join(TILE_HOSTS),
    "connect-src 'self'",
    "font-src 'self'",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'none'",
    "frame-ancestors 'none'",
])
SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    # Tile servers (OSM) ask for a Referer; send only our origin.
    "Referrer-Policy": "strict-origin-when-cross-origin",
}
NO_CACHE = {"Cache-Control": "no-store"}

SESSION_COOKIE = "mk_operator"
SESSION_TTL_S = 12 * 3600
LOGIN_WINDOW_S = 600.0
LOGIN_MAX_FAILURES = 10
CSRF_HEADER = "x-mataklabat"

log = logging.getLogger(__name__)


class OperatorAuth:
    """One shared operator password (OPERATOR_PASSWORD), sessions kept in memory.

    Failed logins are limited for everyone together (the app sits behind a proxy,
    so client addresses are not trustworthy): after LOGIN_MAX_FAILURES wrong
    passwords within LOGIN_WINDOW_S, logins are refused until the window passes.
    """

    def __init__(self, password: str | None, clock=time.monotonic):
        self._password = password
        self._clock = clock
        self._sessions: dict[str, float] = {}
        self._failures: list[float] = []

    @property
    def available(self) -> bool:
        return bool(self._password)

    def locked_for(self) -> float:
        now = self._clock()
        self._failures = [t for t in self._failures if now - t < LOGIN_WINDOW_S]
        if len(self._failures) < LOGIN_MAX_FAILURES:
            return 0.0
        return LOGIN_WINDOW_S - (now - self._failures[0])

    def login(self, password: str) -> str | None:
        if not self.available or self.locked_for() > 0:
            return None
        if not hmac.compare_digest(password.encode("utf-8"), self._password.encode("utf-8")):
            self._failures.append(self._clock())
            return None
        token = secrets.token_urlsafe(32)
        self._sessions[token] = self._clock() + SESSION_TTL_S
        return token

    def valid(self, token: str | None) -> bool:
        if not token:
            return False
        expires = self._sessions.get(token)
        if expires is None:
            return False
        if self._clock() >= expires:
            self._sessions.pop(token, None)
            return False
        return True

    def logout(self, token: str | None) -> None:
        if token:
            self._sessions.pop(token, None)


def _json_field(value: str | None) -> Any:
    return None if not value else json.loads(value)


def create_app(
    settings: Settings,
    store: ReadStore | None = None,
    control: CameraControl | None = None,
    auth: OperatorAuth | None = None,
) -> FastAPI:
    store = store or ReadStore(settings.db_path)
    control = control or CameraControl(settings.control_db_path, settings.cameras, writable=True)
    auth = auth or OperatorAuth(settings.operator_password)
    if not auth.available:
        log.info("OPERATOR_PASSWORD kosong: tombol operator (kamera aktif/nonaktif) dimatikan.")
    cameras = {c.id: c for c in settings.cameras}
    tools = IncidentTools(settings, risk_provider=store.risk)
    hotspot_cache: dict[str, Any] = {"at": -HOTSPOT_CACHE_S, "data": None}
    app = FastAPI(title="MataKlabat", docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        for key, value in SECURITY_HEADERS.items():
            response.headers.setdefault(key, value)
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    # --- helpers ---------------------------------------------------------------------------

    def camera_or_404(camera_id: str):
        cam = cameras.get(camera_id)
        if cam is None:
            raise HTTPException(404, "kamera tidak dikenal")
        return cam

    def monitor_state() -> dict[str, Any]:
        rows = {h["component"]: h for h in store.health()}
        beat = rows.get("monitor")
        age = None
        if beat is not None:
            age = (now_local() - datetime.fromisoformat(beat["ts"])).total_seconds()
        alive = beat is not None and bool(beat["ok"]) and age is not None and age <= MONITOR_STALE_S
        return {"alive": alive, "last_beat": beat["ts"] if beat else None, "age_s": age}

    def camera_view(cam, row: dict[str, Any] | None, monitor_alive: bool, enabled: bool,
                    control_ts: str | None = None) -> dict[str, Any]:
        row = row or {}
        # What the monitor applied; without a row yet, assume it follows the operator.
        active = bool(row.get("enabled", 1)) if row else enabled
        online = bool(row.get("online")) and monitor_alive and enabled and active
        level = row.get("level") or Level.AMAN.value
        if not enabled:
            level = Level.AMAN.value
        return {
            "id": cam.id,
            "name": cam.name,
            "lat": cam.lat,
            "lon": cam.lon,
            "facing_deg": cam.facing_deg,
            "mode": cam.mode,
            "enabled": enabled,
            "control_ts": control_ts,  # when an operator last switched it (None = config default)
            "pending": monitor_alive and enabled != active,
            "online": online,
            "offline_reason": None if online else (row.get("offline_reason") or ("monitor tidak berjalan" if not monitor_alive else "tidak ada data")),
            "level": level,
            "label": Level(level).label,
            "sub_status": row.get("sub_status"),
            "rule": row.get("rule"),
            "explanation": row.get("explanation"),
            "fire_score": row.get("fire_score"),
            "smoke_score": row.get("smoke_score"),
            "last_reasoning": row.get("last_reasoning"),
            "last_llm_ts": row.get("last_llm_ts"),
            "ts": row.get("ts"),
            "snapshot_url": f"/api/cameras/{cam.id}/snapshot.jpg?t={row.get('ts') or ''}" if row.get("last_snapshot") else None,
            "photo_shown": shown_photo(cam) if cam.is_photo else None,
        }

    def all_cameras() -> list[dict[str, Any]]:
        rows = {r["camera_id"]: r for r in store.camera_statuses()}
        alive = monitor_state()["alive"]
        stored = control.rows()
        states = control.states()
        return [
            camera_view(cam, rows.get(cam.id), alive, states[cam.id], (stored.get(cam.id) or {}).get("updated_ts"))
            for cam in settings.cameras
        ]

    # --- operator -----------------------------------------------------------------------------

    def is_operator(request: Request) -> bool:
        return auth.valid(request.cookies.get(SESSION_COOKIE))

    def check_write(request: Request) -> None:
        """Operator session plus same-origin checks for every state-changing request."""
        if request.headers.get(CSRF_HEADER) != "1":
            raise HTTPException(403, "permintaan ditolak")
        origin = request.headers.get("origin")
        host = request.headers.get("x-forwarded-host") or request.headers.get("host")
        if origin and urlsplit(origin).netloc != host:
            raise HTTPException(403, "asal permintaan tidak dikenal")
        if not is_operator(request):
            raise HTTPException(401, "masuk sebagai operator dulu")

    def secure_request(request: Request) -> bool:
        return request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"

    def risk_view() -> dict[str, Any] | None:
        risk = store.risk()
        if risk is None:
            return None
        age = (now_local() - datetime.fromisoformat(risk["fetched_ts"])).total_seconds()
        return {**risk, "age_s": age, "stale": age > 3600 * 1.5, "unknown": age > 6 * 3600}

    def event_view(e: dict[str, Any]) -> dict[str, Any]:
        trace = _json_field(e.get("trace_json")) or {}
        llm = _json_field(e.get("llm_json"))
        return {
            "id": e["id"],
            "ts": e["ts"],
            "camera_id": e.get("camera_id"),
            "level": e["level"],
            "label": Level(e["level"]).label,
            "level_from": trace.get("level_from"),
            "sub_status": e.get("sub_status"),
            "rule": e.get("rule"),
            "fire_score": e.get("fire_score"),
            "smoke_score": e.get("smoke_score"),
            "explanation": trace.get("explanation"),
            "llm": llm,
            "trace": trace,
            "snapshot_url": f"/api/events/{e['id']}/snapshot.jpg" if e.get("snapshot_path") else None,
        }

    # --- pages -------------------------------------------------------------------------------

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC_DIR / "index.html", headers=NO_CACHE)

    @app.get("/incident/{incident_id}", include_in_schema=False)
    def incident_page(incident_id: int):
        return FileResponse(STATIC_DIR / "incident.html", headers=NO_CACHE)

    @app.get("/health", include_in_schema=False)
    def health_page():
        return FileResponse(STATIC_DIR / "health.html", headers=NO_CACHE)

    # --- API ------------------------------------------------------------------------------------

    @app.get("/api/status")
    def status():
        cams = all_cameras()
        counts = {"normal": 0, "check": 0, "fire": 0, "offline": 0, "disabled": 0}
        for c in cams:
            if not c["enabled"]:
                key = "disabled"
            elif not c["online"]:
                key = "offline"
            else:
                key = {"AMAN": "normal", "WASPADA": "check", "BAHAYA": "fire"}[c["level"]]
            counts[key] += 1
        open_incidents = store.incidents("open")
        return {
            "now": iso(),
            "monitor": monitor_state(),
            "llm_enabled": settings.llm_enabled,
            "risk": risk_view(),
            "counts": counts,
            "cameras": cams,
            "open_incidents": [
                {**i, "camera_name": cameras[i["camera_id"]].name if i["camera_id"] in cameras else i["camera_id"]}
                for i in open_incidents
            ],
        }

    @app.get("/api/cameras")
    def list_cameras():
        return all_cameras()

    @app.get("/api/session")
    def session(request: Request):
        return {"operator": is_operator(request), "available": auth.available}

    @app.post("/api/login")
    def login(request: Request, response: Response, payload: dict = Body(...)):
        if request.headers.get(CSRF_HEADER) != "1":
            raise HTTPException(403, "permintaan ditolak")
        if not auth.available:
            raise HTTPException(404, "mode operator tidak diaktifkan (OPERATOR_PASSWORD kosong)")
        wait = auth.locked_for()
        if wait > 0:
            raise HTTPException(429, f"terlalu banyak percobaan, coba lagi dalam {int(wait // 60) + 1} menit")
        password = payload.get("password")
        token = auth.login(password) if isinstance(password, str) else None
        if token is None:
            log.warning("Login operator gagal.")
            raise HTTPException(401, "password salah")
        log.info("Operator masuk.")
        response.set_cookie(
            SESSION_COOKIE, token, max_age=SESSION_TTL_S, httponly=True, samesite="strict",
            secure=secure_request(request), path="/",
        )
        return {"operator": True}

    @app.post("/api/logout")
    def logout(request: Request, response: Response):
        auth.logout(request.cookies.get(SESSION_COOKIE))
        response.delete_cookie(SESSION_COOKIE, path="/")
        return {"operator": False}

    @app.post("/api/cameras/{camera_id}/enabled")
    def set_enabled(camera_id: str, request: Request, payload: dict = Body(...)):
        check_write(request)
        camera_or_404(camera_id)
        enabled = payload.get("enabled")
        if not isinstance(enabled, bool):
            raise HTTPException(422, "'enabled' harus true atau false")
        control.set_enabled(camera_id, enabled)
        return {"id": camera_id, "enabled": enabled}

    @app.get("/api/gallery")
    def gallery(request: Request):
        if not is_operator(request):
            raise HTTPException(401, "masuk sebagai operator dulu")
        return [{"name": p.name, "url": f"/api/gallery/{p.name}", "thumb_url": f"/api/gallery/{p.name}?thumb=1"}
                for p in gallery_photos(settings)]

    @app.get("/api/gallery/{name}")
    def gallery_image(name: str, request: Request, thumb: bool = False):
        if not is_operator(request):
            raise HTTPException(401, "masuk sebagai operator dulu")
        path = gallery_photo(settings, name)
        if path is None:
            raise HTTPException(404, "foto tidak ada di galeri")
        cache = {"Cache-Control": "private, max-age=3600"}
        if thumb:
            data = thumbnail(path)
            if data is None:
                raise HTTPException(404, "foto tidak bisa dibaca")
            return Response(data, media_type="image/jpeg", headers=cache)
        return FileResponse(path, headers=cache)

    @app.post("/api/cameras/{camera_id}/photo")
    def choose_photo(camera_id: str, request: Request, payload: dict = Body(...)):
        check_write(request)
        cam = camera_or_404(camera_id)
        if not cam.is_photo:
            raise HTTPException(400, "kamera ini bukan kamera mode foto")
        name = payload.get("name")
        path = gallery_photo(settings, name) if isinstance(name, str) else None
        if path is None:
            raise HTTPException(404, "foto tidak ada di galeri")
        show_photo(cam, path)
        log.info("%s menampilkan foto galeri %s.", cam.id, path.name)
        return {"id": camera_id, "photo": path.name}

    @app.get("/api/cameras/{camera_id}/snapshot.jpg")
    def camera_snapshot(camera_id: str):
        camera_or_404(camera_id)
        path = settings.snapshot_dir / camera_id / "latest.jpg"
        if not path.is_file():
            raise HTTPException(404, "belum ada snapshot")
        return FileResponse(path, media_type="image/jpeg", headers=NO_CACHE)

    @app.get("/api/events/{event_id}/snapshot.jpg")
    def event_snapshot(event_id: int):
        relative = store.event_snapshot_path(event_id)
        if not relative:
            raise HTTPException(404, "tidak ada foto")
        root = settings.snapshot_dir.resolve()
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise HTTPException(404, "tidak ada foto")
        return FileResponse(path, media_type="image/jpeg")

    @app.get("/api/events")
    def events(camera: str | None = None, minutes: int = Query(30, ge=1, le=1440)):
        if camera:
            camera_or_404(camera)
        since = iso(now_local() - timedelta(minutes=minutes))
        return [event_view(e) for e in store.events(camera, since)]

    @app.get("/api/incidents")
    def incidents(state: str | None = Query(None, pattern="^(open|closed)$")):
        return store.incidents(state)

    @app.get("/api/incidents/{incident_id}")
    def incident(incident_id: int):
        row = store.incident(incident_id)
        if row is None:
            raise HTTPException(404, "insiden tidak ditemukan")
        cam = cameras.get(row["camera_id"])
        outbox = store.outbox(incident_id=incident_id)
        steps = _json_field(row.pop("agent_steps_json", None)) or []
        return {
            **row,
            "camera_name": cam.name if cam else row["camera_id"],
            "agent_steps": steps,
            "events": [event_view(e) for e in store.incident_events(row)],
            "messages": [
                {k: m[k] for k in ("id", "kind", "status", "attempts", "last_error", "created_ts", "sent_ts", "text")}
                for m in outbox
            ],
        }

    @app.get("/api/risk")
    def risk(days: int = Query(30, ge=1, le=120)):
        return {"current": risk_view(), "daily": store.risk_daily(days)}

    @app.get("/api/outbox")
    def outbox(limit: int = Query(30, ge=1, le=200)):
        return [
            {k: m[k] for k in ("id", "kind", "camera_id", "incident_id", "status", "attempts", "last_error", "created_ts", "sent_ts", "text")}
            for m in store.outbox(limit)
        ]

    @app.get("/api/map")
    def map_data():
        res = settings.resources
        return {
            "center": settings.risk_point,
            "cameras": [{"id": c.id, "name": c.name, "lat": c.lat, "lon": c.lon, "facing_deg": c.facing_deg} for c in settings.cameras],
            "villages": [{"name": v.name, "lat": v.lat, "lon": v.lon} for v in res.villages],
            "resources": [{"name": r.name, "kind": r.kind, "lat": r.lat, "lon": r.lon} for r in res.resources],
            "reference_points": [{"name": p.name, "lat": p.lat, "lon": p.lon} for p in res.reference_points],
        }

    @app.get("/api/hotspots")
    def hotspots():
        now = time.monotonic()
        if now - hotspot_cache["at"] >= HOTSPOT_CACHE_S or hotspot_cache["data"] is None:
            lat, lon = settings.risk_point
            hotspot_cache["data"] = tools.get_satellite_hotspots(lat, lon, radius_km=25)
            hotspot_cache["at"] = now
        return hotspot_cache["data"]

    @app.get("/api/health")
    def health():
        return {
            "now": iso(),
            "monitor": monitor_state(),
            "components": store.health(),
            "cameras": all_cameras(),
            "outbox_pending": sum(1 for m in store.outbox(200) if m["status"] == "pending"),
            "config": {
                "llm_enabled": settings.llm_enabled,
                "llm_model": settings.llm_model,
                "telegram_configured": bool(settings.telegram_bot_token and settings.telegram_chat_id),
                "auto_send_alert": settings.auto_send_alert,
                "firms_configured": bool(settings.firms_map_key),
                "prompt_version": settings.prompt_version,
            },
        }

    def version() -> str:
        beat = monitor_state()["last_beat"] or ""
        statuses = "|".join(f"{r['camera_id']}:{r['ts']}:{r['level']}:{r['online']}" for r in store.camera_statuses())
        statuses += "|" + ",".join(f"{k}:{v['updated_ts']}" for k, v in sorted(control.rows().items()))
        risk = store.risk() or {}
        return "/".join([
            str(store.latest_event_id()), store.latest_outbox_change(), statuses, beat[:16], risk.get("fetched_ts", ""),
        ])

    @app.get("/api/stream")
    async def stream(request: Request):
        async def events_gen():
            last, last_sent = None, time.monotonic()
            yield "retry: 3000\n\n"
            while True:
                if await request.is_disconnected():
                    break
                current = await asyncio.to_thread(version)
                if current != last:
                    last, last_sent = current, time.monotonic()
                    yield f"event: update\ndata: {json.dumps({'ts': iso()})}\n\n"
                elif time.monotonic() - last_sent >= SSE_KEEPALIVE_S:
                    last_sent = time.monotonic()
                    yield ": keepalive\n\n"
                await asyncio.sleep(SSE_POLL_S)

        return StreamingResponse(
            events_gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code, headers=SECURITY_HEADERS)

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


def run_web(settings: Settings, host: str | None = None, port: int | None = None) -> None:
    import logging

    import uvicorn

    host = host or settings.web_host
    port = port or settings.web_port
    log = logging.getLogger(__name__)
    if host not in ("127.0.0.1", "localhost", "::1"):
        log.warning(
            "Website dibuka ke jaringan (%s). Siapa pun di jaringan yang sama bisa MELIHAT dashboard; "
            "tombol kamera hanya untuk operator yang masuk dengan OPERATOR_PASSWORD.", host,
        )
    log.info("Website: http://%s:%d", "127.0.0.1" if host in ("0.0.0.0", "::") else host, port)
    uvicorn.run(create_app(settings), host=host, port=port, log_level="warning", access_log=False)
