"""Message templates for Telegram and the web (Spec §8.2).

Everything here is deterministic: the text is built from the decision trace and
the data, never written freely by the LLM. Only the LLM's own short reasoning is
quoted, in quotation marks and shortened.
"""

from __future__ import annotations

from datetime import datetime

from mataklabat.config import CameraConfig
from mataklabat.decision import Decision, Level
from mataklabat.prompts import compass_name

CAPTION_LIMIT = 1024  # Telegram sendPhoto caption
MESSAGE_LIMIT = 4096  # Telegram sendMessage text
QUOTE_LIMIT = 160

SUB_STATUS_LABELS = {
    "unverified": "belum terverifikasi AI",
    "POTENSI": "potensi (faktor risiko terlihat)",
    "rejected_lookalike": "AI menolak: mirip kabut/senja/lampu",
}
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des")
_HAZARD_WORDS = {
    "smoke": "asap",
    "flame": "api",
    "smoke_and_flame": "api dan asap",
    "haze": "kabut asap",
    "uncertain": "tidak pasti",
    "none": "tidak ada api/asap",
}
_LOOKALIKE_WORDS = {
    "none": "bukan kabut/awan atau cahaya",
    "fog_cloud": "mirip kabut/awan",
    "sunset_glare": "mirip cahaya senja",
    "artificial_light": "mirip lampu",
    "dust": "mirip debu",
    "steam": "mirip uap",
    "other": "mirip objek lain",
}


def status_label(level: Level | str) -> str:
    return Level(level).label


def format_time(ts: datetime) -> str:
    return f"{ts.day} {_MONTHS[ts.month - 1]} {ts.year}, {ts:%H:%M} WITA"


def shorten(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def fit(text: str, limit: int) -> str:
    """Cut a message to Telegram's limit at a line boundary when possible."""
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    nl = cut.rfind("\n")
    return (cut[:nl] if nl > limit // 2 else cut).rstrip() + "…"


def wind_line(risk: dict | None) -> str | None:
    now = (risk or {}).get("now") or {}
    speed, direction = now.get("wind_kmh"), now.get("wind_dir_deg")
    if speed is None or direction is None:
        return None
    toward = compass_name((direction + 180) % 360)
    return f"Angin {speed:.0f} km/j dari {compass_name(direction)} → api cenderung ke {toward}"


def risk_line(risk: dict | None) -> str:
    if not risk:
        return "Risiko kawasan: tidak diketahui (data cuaca belum tersedia)"
    return (
        f"Risiko kawasan: {risk['level'].upper()} (karena {risk['driver_text']}, "
        f"FWI {risk['codes']['fwi']:.1f}, {risk['days_without_rain']} hari tanpa hujan)"
    )


def _why_lines(decision: Decision) -> list[str]:
    local = decision.trace["inputs"]["local"]
    lines = [
        f"• Detektor kamera: api {local['fire_score']:.2f}, asap {local['smoke_score']:.2f} "
        f"(aktif {local['t1_hits']} frame terakhir)"
    ]
    v = decision.verdict
    if v is not None and v.ok:
        lines.append(
            f"• Verifikasi AI: {_HAZARD_WORDS.get(v.hazard_type, v.hazard_type)}, "
            f"keyakinan {v.confidence:.2f}, {_LOOKALIKE_WORDS.get(v.lookalike, v.lookalike)}"
        )
        if v.reasoning:
            lines.append(f'  "{shorten(v.reasoning, QUOTE_LIMIT)}"')
    elif decision.sub_status == "unverified":
        lines.append("• Verifikasi AI: tidak tersedia saat ini")
    lines.append(f"• Aturan {decision.rule}: {decision.explanation}")
    return lines


def _data_lines(risk: dict | None) -> list[str]:
    lines = [f"• {risk_line(risk)}"]
    wind = wind_line(risk)
    if wind:
        lines.append(f"• {wind}")
    return lines


def _footer(public_url: str | None, incident_id: int | None = None) -> list[str]:
    if not public_url:
        return []
    path = f"/incident/{incident_id}" if incident_id else "/"
    return ["", f"Detail: {public_url.rstrip('/')}{path}"]


def fire_alert(decision: Decision, camera: CameraConfig, risk: dict | None,
               public_url: str | None = None, incident_id: int | None = None) -> str:
    lines = [
        f"🔴 KEBAKARAN TERDETEKSI — {camera.id} {camera.name}",
        format_time(decision.ts),
        "",
        "Kenapa:",
        *_why_lines(decision),
        "",
        "Data yang dipakai:",
        *_data_lines(risk),
        "",
        "Tindakan: verifikasi lapangan segera. Laporan lengkap menyusul.",
        *_footer(public_url, incident_id),
    ]
    return fit("\n".join(lines), CAPTION_LIMIT)


def check_alert(decision: Decision, camera: CameraConfig, risk: dict | None, public_url: str | None = None) -> str:
    sub = SUB_STATUS_LABELS.get(decision.sub_status or "")
    title = f"🟡 PERLU DICEK — {camera.id} {camera.name}"
    lines = [
        title + (f" ({sub})" if sub else ""),
        format_time(decision.ts),
        "Belum pasti, mohon dicek.",
        "",
        "Kenapa:",
        *_why_lines(decision),
        "",
        "Data yang dipakai:",
        *_data_lines(risk),
        *_footer(public_url),
    ]
    return fit("\n".join(lines), CAPTION_LIMIT)


def risk_rise_alert(risk: dict, previous_level: str | None, public_url: str | None = None) -> str:
    change = f"naik dari {previous_level} " if previous_level else ""
    lines = [
        f"🟠 RISIKO KEBAKARAN KAWASAN {change}menjadi {risk['level'].upper()}",
        f"Gunung Klabat, {risk['date']}",
        "",
        *_risk_detail(risk),
        *_footer(public_url),
    ]
    return fit("\n".join(lines), MESSAGE_LIMIT)


def morning_summary(risk: dict | None, cameras: list[dict], when: datetime, public_url: str | None = None) -> str:
    lines = [f"☀️ RINGKASAN PAGI MATAKLABAT — {format_time(when)}", ""]
    if risk:
        lines += [f"Risiko kawasan hari ini: {risk['level'].upper()}", *_risk_detail(risk)]
    else:
        lines.append("Risiko kawasan: tidak diketahui (data cuaca belum tersedia).")
    lines += ["", "Status kamera:"]
    for cam in cameras:
        state = status_label(cam["level"]) if cam.get("online") else "Offline"
        lines.append(f"• {cam['camera_id']} {cam.get('name') or ''}: {state}")
    lines += _footer(public_url)
    return fit("\n".join(lines), MESSAGE_LIMIT)


def _risk_detail(risk: dict) -> list[str]:
    levels = risk.get("indicator_levels", {})
    codes = risk["codes"]
    lines = [
        f"• Penentu: {risk['driver_text']}",
        f"• Kekeringan tanah (DC {codes['dc']:.0f}): {levels.get('dc', '-')}",
        f"• Mudah menyala (FFMC {codes['ffmc']:.0f}): {levels.get('ffmc', '-')}",
        f"• Sulitnya pemadaman (ISI {codes['isi']:.1f}): {levels.get('isi', '-')}",
        f"• {risk['days_without_rain']} hari tanpa hujan, FWI {codes['fwi']:.1f}",
    ]
    wind = wind_line(risk)
    if wind:
        lines.append(f"• {wind}")
    if risk.get("forecast"):
        days = ", ".join(f"{d['date'][5:]} {d['level']}" for d in risk["forecast"])
        lines.append(f"• Prakiraan: {days}")
    lines.append(f"Saran: {risk['advice']}")
    return lines


def report_message(camera: CameraConfig, incident_id: int, report_md: str) -> str:
    """Markdown report as plain Telegram text: '## Title' becomes an upper-case line."""
    lines = [f"📋 LAPORAN INSIDEN #{incident_id} · {camera.id} {camera.name}", ""]
    for raw in report_md.splitlines():
        line = raw.rstrip()
        if line.startswith("#"):
            line = line.lstrip("#").strip().upper()
        line = line.replace("**", "")
        if line.startswith("_") and line.endswith("_") and len(line) > 2:
            line = line[1:-1]
        lines.append(line)
    return fit("\n".join(lines).strip(), MESSAGE_LIMIT)
