"""SQLite storage (Spec §11). The monitor is the only writer; the web only reads.

All timestamps are ISO-8601 strings in Asia/Makassar (+08:00), so they sort and
compare correctly as text.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

from mataklabat.config import now_local

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  camera_id TEXT NOT NULL,
  level TEXT NOT NULL,
  sub_status TEXT,
  fire_score REAL, smoke_score REAL,
  llm_json TEXT,
  risk_level TEXT,
  fwi REAL,
  rule TEXT,
  trace_json TEXT NOT NULL,
  snapshot_path TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_cam_ts ON events(camera_id, ts);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);

CREATE TABLE IF NOT EXISTS incidents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  opened_ts TEXT NOT NULL,
  closed_ts TEXT,
  camera_id TEXT NOT NULL,
  peak_level TEXT NOT NULL,
  trigger_event_id INTEGER REFERENCES events(id),
  report_md TEXT,
  agent_steps_json TEXT,
  report_source TEXT,
  alert_sent INTEGER DEFAULT 0,
  alert_outbox_id INTEGER,
  report_outbox_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_incidents_open ON incidents(closed_ts);

CREATE TABLE IF NOT EXISTS camera_status (
  camera_id TEXT PRIMARY KEY,
  name TEXT,
  mode TEXT,
  ts TEXT NOT NULL,
  level TEXT NOT NULL DEFAULT 'AMAN',
  sub_status TEXT,
  rule TEXT,
  explanation TEXT,
  fire_score REAL, smoke_score REAL,
  risk_level TEXT,
  last_snapshot TEXT,
  last_reasoning TEXT,
  last_llm_ts TEXT,
  online INTEGER NOT NULL DEFAULT 0,
  offline_reason TEXT
);

CREATE TABLE IF NOT EXISTS risk_daily (
  date TEXT PRIMARY KEY,
  temp REAL, rh REAL, wind REAL, rain24 REAL,
  ffmc REAL, dmc REAL, dc REAL, isi REAL, bui REAL, fwi REAL,
  category TEXT, driver TEXT,
  source TEXT NOT NULL,
  fetched_ts TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS risk_current (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  fetched_ts TEXT NOT NULL,
  json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS outbox (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  camera_id TEXT,
  incident_id INTEGER,
  text TEXT NOT NULL,
  photo_path TEXT,
  status TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  next_attempt_ts TEXT,
  last_error TEXT,
  created_ts TEXT NOT NULL,
  sent_ts TEXT
);
CREATE INDEX IF NOT EXISTS idx_outbox_due ON outbox(status, next_attempt_ts);

CREATE TABLE IF NOT EXISTS component_health (
  component TEXT PRIMARY KEY,
  ok INTEGER NOT NULL,
  detail TEXT,
  ts TEXT NOT NULL
);
"""

OUTBOX_PENDING = "pending"
OUTBOX_SENT = "sent"
OUTBOX_FAILED = "failed"
OUTBOX_DRY_RUN = "dry_run"


def iso(ts: datetime | None = None) -> str:
    return (ts or now_local()).isoformat(timespec="seconds")


def _connect(path: Path, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=5)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, timeout=10, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    return conn


class Storage:
    """Writer used by the monitor process. Thread-safe through one lock."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._conn = _connect(self.path)
        self._lock = threading.Lock()
        with self._tx() as c:
            c.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    # --- events and camera status ----------------------------------------------------

    def insert_event(
        self,
        *,
        ts: datetime,
        camera_id: str,
        level: str,
        sub_status: str | None,
        fire_score: float,
        smoke_score: float,
        llm: dict[str, Any] | None,
        risk_level: str | None,
        fwi: float | None,
        rule: str,
        trace: dict[str, Any],
        snapshot_path: str | None,
    ) -> int:
        with self._tx() as c:
            cur = c.execute(
                "INSERT INTO events (ts, camera_id, level, sub_status, fire_score, smoke_score, llm_json,"
                " risk_level, fwi, rule, trace_json, snapshot_path) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    iso(ts), camera_id, level, sub_status, fire_score, smoke_score,
                    None if llm is None else json.dumps(llm, ensure_ascii=False),
                    risk_level, fwi, rule, json.dumps(trace, ensure_ascii=False), snapshot_path,
                ),
            )
            return int(cur.lastrowid)

    def upsert_camera_status(self, camera_id: str, **fields: Any) -> None:
        fields = {"ts": iso(), **fields}
        if isinstance(fields.get("ts"), datetime):
            fields["ts"] = iso(fields["ts"])
        cols = ", ".join(fields)
        marks = ", ".join("?" for _ in fields)
        updates = ", ".join(f"{k}=excluded.{k}" for k in fields)
        with self._tx() as c:
            c.execute(
                f"INSERT INTO camera_status (camera_id, {cols}) VALUES (?, {marks})"
                f" ON CONFLICT(camera_id) DO UPDATE SET {updates}",
                (camera_id, *fields.values()),
            )

    # --- incidents -------------------------------------------------------------------------

    def open_incident(self, camera_id: str, ts: datetime, level: str, trigger_event_id: int | None) -> int:
        with self._tx() as c:
            cur = c.execute(
                "INSERT INTO incidents (opened_ts, camera_id, peak_level, trigger_event_id) VALUES (?,?,?,?)",
                (iso(ts), camera_id, level, trigger_event_id),
            )
            return int(cur.lastrowid)

    def open_incident_id(self, camera_id: str) -> int | None:
        with self._tx() as c:
            row = c.execute(
                "SELECT id FROM incidents WHERE camera_id=? AND closed_ts IS NULL ORDER BY id DESC LIMIT 1",
                (camera_id,),
            ).fetchone()
        return None if row is None else int(row["id"])

    def close_incident(self, incident_id: int, ts: datetime) -> None:
        with self._tx() as c:
            c.execute("UPDATE incidents SET closed_ts=? WHERE id=?", (iso(ts), incident_id))

    def update_incident(self, incident_id: int, **fields: Any) -> None:
        sets = ", ".join(f"{k}=?" for k in fields)
        with self._tx() as c:
            c.execute(f"UPDATE incidents SET {sets} WHERE id=?", (*fields.values(), incident_id))

    def incident(self, incident_id: int) -> dict[str, Any] | None:
        with self._tx() as c:
            row = c.execute("SELECT * FROM incidents WHERE id=?", (incident_id,)).fetchone()
        return None if row is None else dict(row)

    def recent_events(self, camera_id: str, minutes: int) -> list[dict[str, Any]]:
        since = iso(now_local() - timedelta(minutes=minutes))
        with self._tx() as c:
            rows = c.execute(
                "SELECT ts, level, sub_status, rule, fire_score, smoke_score, trace_json FROM events"
                " WHERE camera_id=? AND ts>=? ORDER BY id",
                (camera_id, since),
            ).fetchall()
        return [dict(r) for r in rows]

    # --- risk ----------------------------------------------------------------------------------

    def save_risk(self, snapshot) -> None:
        """Store today's risk, the history and the forecast (a risk.RiskSnapshot)."""
        fetched = iso(snapshot.fetched_at)
        rows = []
        for day in (*snapshot.history, *snapshot.forecast):
            w, k = day.weather, day.codes
            rows.append((
                day.day.isoformat(), w.temp_c, w.rh_pct, w.wind_kmh, w.rain_mm,
                k.ffmc, k.dmc, k.dc, k.isi, k.bui, k.fwi, day.level, day.driver,
                "observed" if day.observed else "forecast", fetched,
            ))
        current = risk_to_dict(snapshot)
        with self._tx() as c:
            c.executemany(
                "INSERT INTO risk_daily VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(date) DO UPDATE SET temp=excluded.temp, rh=excluded.rh, wind=excluded.wind,"
                " rain24=excluded.rain24, ffmc=excluded.ffmc, dmc=excluded.dmc, dc=excluded.dc,"
                " isi=excluded.isi, bui=excluded.bui, fwi=excluded.fwi, category=excluded.category,"
                " driver=excluded.driver, source=excluded.source, fetched_ts=excluded.fetched_ts",
                rows,
            )
            c.execute(
                "INSERT INTO risk_current (id, fetched_ts, json) VALUES (1, ?, ?)"
                " ON CONFLICT(id) DO UPDATE SET fetched_ts=excluded.fetched_ts, json=excluded.json",
                (fetched, json.dumps(current, ensure_ascii=False)),
            )

    # --- outbox --------------------------------------------------------------------------------

    def enqueue(
        self,
        kind: str,
        text: str,
        *,
        camera_id: str | None = None,
        incident_id: int | None = None,
        photo_path: str | None = None,
        status: str = OUTBOX_PENDING,
        created: datetime | None = None,
    ) -> int:
        now = iso(created)
        with self._tx() as c:
            cur = c.execute(
                "INSERT INTO outbox (kind, camera_id, incident_id, text, photo_path, status, next_attempt_ts,"
                " created_ts) VALUES (?,?,?,?,?,?,?,?)",
                (kind, camera_id, incident_id, text, photo_path, status, now, now),
            )
            return int(cur.lastrowid)

    def due_outbox(self, now: datetime, limit: int = 5) -> list[dict[str, Any]]:
        with self._tx() as c:
            rows = c.execute(
                "SELECT * FROM outbox WHERE status=? AND next_attempt_ts<=? ORDER BY id LIMIT ?",
                (OUTBOX_PENDING, iso(now), limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def mark_sent(self, outbox_id: int) -> None:
        with self._tx() as c:
            c.execute(
                "UPDATE outbox SET status=?, sent_ts=?, attempts=attempts+1, last_error=NULL WHERE id=?",
                (OUTBOX_SENT, iso(), outbox_id),
            )

    def mark_retry(self, outbox_id: int, error: str, next_attempt: datetime, give_up: bool) -> None:
        with self._tx() as c:
            c.execute(
                "UPDATE outbox SET status=?, attempts=attempts+1, last_error=?, next_attempt_ts=? WHERE id=?",
                (OUTBOX_FAILED if give_up else OUTBOX_PENDING, error[:300], iso(next_attempt), outbox_id),
            )

    def outbox_item(self, outbox_id: int) -> dict[str, Any] | None:
        with self._tx() as c:
            row = c.execute("SELECT * FROM outbox WHERE id=?", (outbox_id,)).fetchone()
        return None if row is None else dict(row)

    def outbox_count_since(self, kind: str, since: datetime) -> int:
        with self._tx() as c:
            row = c.execute(
                "SELECT COUNT(*) AS n FROM outbox WHERE kind=? AND created_ts>=?", (kind, iso(since))
            ).fetchone()
        return int(row["n"])

    def current_risk_level(self) -> str | None:
        with self._tx() as c:
            row = c.execute("SELECT json FROM risk_current WHERE id=1").fetchone()
        return None if row is None else json.loads(row["json"]).get("level")

    def camera_rows(self) -> list[dict[str, Any]]:
        with self._tx() as c:
            return [dict(r) for r in c.execute("SELECT * FROM camera_status ORDER BY camera_id").fetchall()]

    # --- health and retention -------------------------------------------------------------

    def set_health(self, component: str, ok: bool | None, detail: str = "") -> None:
        """ok=None marks a component that is switched off on purpose (stored as -1)."""
        with self._tx() as c:
            c.execute(
                "INSERT INTO component_health (component, ok, detail, ts) VALUES (?,?,?,?)"
                " ON CONFLICT(component) DO UPDATE SET ok=excluded.ok, detail=excluded.detail, ts=excluded.ts",
                (component, -1 if ok is None else int(ok), detail[:300], iso()),
            )

    def prune(self, now: datetime, keep_days: int) -> int:
        cutoff = iso(now - timedelta(days=keep_days))
        with self._tx() as c:
            cur = c.execute("DELETE FROM events WHERE ts < ? AND id NOT IN"
                            " (SELECT trigger_event_id FROM incidents WHERE trigger_event_id IS NOT NULL)",
                            (cutoff,))
            c.execute("DELETE FROM outbox WHERE created_ts < ? AND status != ?", (cutoff, OUTBOX_PENDING))
            return cur.rowcount


def risk_to_dict(snapshot) -> dict[str, Any]:
    today = snapshot.today
    return {
        "fetched_ts": iso(snapshot.fetched_at),
        "date": today.day.isoformat(),
        "level": today.level,
        "driver": today.driver,
        "driver_text": snapshot.driver_text,
        "advice": snapshot.advice,
        "observed": today.observed,
        "indicator_levels": today.indicator_levels,
        "codes": {k: round(v, 1) for k, v in asdict(today.codes).items()},
        "weather": asdict(today.weather),
        "days_without_rain": snapshot.days_without_rain,
        "now": {
            "temp_c": snapshot.now_temp_c,
            "rh_pct": snapshot.now_rh_pct,
            "wind_kmh": snapshot.now_wind_kmh,
            "wind_dir_deg": snapshot.now_wind_dir_deg,
        },
        "forecast": [
            {"date": d.day.isoformat(), "level": d.level, "driver": d.driver, "fwi": round(d.codes.fwi, 1)}
            for d in snapshot.forecast
        ],
    }


class ReadStore:
    """Read-only queries for the web process. Opens a short-lived connection per call."""

    def __init__(self, path: Path):
        self.path = Path(path)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection | None]:
        if not self.path.is_file():
            yield None
            return
        conn = _connect(self.path, readonly=True)
        try:
            yield conn
        finally:
            conn.close()

    def _all(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        with self._conn() as c:
            if c is None:
                return []
            try:
                return [dict(r) for r in c.execute(sql, params).fetchall()]
            except sqlite3.OperationalError:
                return []  # schema not created yet

    def _one(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        rows = self._all(sql, params)
        return rows[0] if rows else None

    def camera_statuses(self) -> list[dict[str, Any]]:
        return self._all("SELECT * FROM camera_status ORDER BY camera_id")

    def camera_status(self, camera_id: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM camera_status WHERE camera_id=?", (camera_id,))

    def risk(self) -> dict[str, Any] | None:
        row = self._one("SELECT json FROM risk_current WHERE id=1")
        return None if row is None else json.loads(row["json"])

    def risk_daily(self, days: int = 30) -> list[dict[str, Any]]:
        rows = self._all("SELECT * FROM risk_daily ORDER BY date DESC LIMIT ?", (days,))
        return list(reversed(rows))

    def events(self, camera_id: str | None, since: str, limit: int = 500) -> list[dict[str, Any]]:
        sql = ("SELECT id, ts, camera_id, level, sub_status, rule, fire_score, smoke_score, risk_level,"
               " llm_json, trace_json, snapshot_path FROM events WHERE ts>=?")
        params: tuple = (since,)
        if camera_id:
            sql += " AND camera_id=?"
            params += (camera_id,)
        return self._all(sql + " ORDER BY id DESC LIMIT ?", params + (limit,))

    def incidents(self, state: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        where = {"open": " WHERE closed_ts IS NULL", "closed": " WHERE closed_ts IS NOT NULL"}.get(state or "", "")
        return self._all(f"SELECT * FROM incidents{where} ORDER BY id DESC LIMIT ?", (limit,))

    def incident(self, incident_id: int) -> dict[str, Any] | None:
        return self._one("SELECT * FROM incidents WHERE id=?", (incident_id,))

    def incident_events(self, incident: dict[str, Any]) -> list[dict[str, Any]]:
        end = incident.get("closed_ts") or "9999"
        start = iso(datetime.fromisoformat(incident["opened_ts"]) - timedelta(minutes=10))
        return self._all(
            "SELECT id, ts, level, sub_status, rule, fire_score, smoke_score, llm_json, trace_json, snapshot_path"
            " FROM events WHERE camera_id=? AND ts>=? AND ts<=? ORDER BY id",
            (incident["camera_id"], start, end),
        )

    def outbox(self, limit: int = 30, incident_id: int | None = None) -> list[dict[str, Any]]:
        if incident_id is not None:
            return self._all("SELECT * FROM outbox WHERE incident_id=? ORDER BY id", (incident_id,))
        return self._all("SELECT * FROM outbox ORDER BY id DESC LIMIT ?", (limit,))

    def health(self) -> list[dict[str, Any]]:
        return self._all("SELECT * FROM component_health ORDER BY component")

    def event_snapshot_path(self, event_id: int) -> str | None:
        row = self._one("SELECT snapshot_path FROM events WHERE id=?", (event_id,))
        return None if row is None else row["snapshot_path"]

    def latest_event_id(self) -> int:
        row = self._one("SELECT MAX(id) AS id FROM events")
        return int(row["id"]) if row and row["id"] is not None else 0

    def latest_outbox_change(self) -> str:
        row = self._one("SELECT MAX(COALESCE(sent_ts, created_ts)) AS ts FROM outbox")
        return (row or {}).get("ts") or ""
