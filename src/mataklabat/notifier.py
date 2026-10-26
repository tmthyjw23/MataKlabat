"""Telegram delivery through the outbox table (Spec §8.3).

Messages are stored first and sent by `OutboxSender`, so a network outage or a
restart never loses an alert. The bot token only ever appears in the request
URL, which is never logged or stored.
"""

from __future__ import annotations

import logging
import threading
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable

import requests

from mataklabat.config import now_local
from mataklabat.messages import CAPTION_LIMIT, MESSAGE_LIMIT, fit
from mataklabat.storage import Storage

log = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"
BACKOFF_S = (5, 15, 60, 300)
MAX_ATTEMPTS = 10
POLL_S = 2.0


class TelegramError(Exception):
    def __init__(self, message: str, *, permanent: bool = False, retry_after: float | None = None):
        super().__init__(message)
        self.permanent = permanent
        self.retry_after = retry_after


class TelegramClient:
    def __init__(self, token: str, chat_id: str, session: Any = requests, timeout: float = 20.0):
        self._token = token
        self.chat_id = chat_id
        self._session = session
        self.timeout = timeout

    def send(self, text: str, photo_path: str | None = None) -> None:
        if photo_path and Path(photo_path).is_file():
            with open(photo_path, "rb") as fh:
                self._call(
                    "sendPhoto",
                    data={"chat_id": self.chat_id, "caption": fit(text, CAPTION_LIMIT)},
                    files={"photo": (Path(photo_path).name, fh, "image/jpeg")},
                )
        else:
            self._call("sendMessage", data={"chat_id": self.chat_id, "text": fit(text, MESSAGE_LIMIT)})

    def _call(self, method: str, **kwargs: Any) -> dict[str, Any]:
        url = f"{TELEGRAM_API}/bot{self._token}/{method}"
        try:
            resp = self._session.post(url, timeout=self.timeout, **kwargs)
        except requests.RequestException as exc:
            # The exception text contains the URL (and so the token): report the type only.
            raise TelegramError(f"jaringan: {type(exc).__name__}") from None
        try:
            data = resp.json()
        except ValueError:
            data = {}
        if resp.status_code == 200 and data.get("ok"):
            return data
        description = str(data.get("description") or f"HTTP {resp.status_code}")
        if resp.status_code == 429:
            retry_after = (data.get("parameters") or {}).get("retry_after")
            raise TelegramError(description, retry_after=float(retry_after or 30))
        permanent = 400 <= resp.status_code < 500
        raise TelegramError(description, permanent=permanent)


class OutboxSender:
    """Background thread that delivers pending outbox rows with retry and backoff."""

    def __init__(
        self,
        storage: Storage,
        client: TelegramClient | None,
        poll_s: float = POLL_S,
        clock: Callable = now_local,
    ):
        self.storage = storage
        self.client = client
        self.poll_s = poll_s
        self._clock = clock
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> OutboxSender:
        if self.client is None:
            self.storage.set_health("telegram", False, "Telegram belum dikonfigurasi (pesan disimpan sebagai mode kering)")
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="outbox", daemon=True)
        self._thread.start()
        return self

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)

    def send_due(self) -> int:
        """Try every pending message that is due. Returns how many were sent."""
        if self.client is None:
            return 0
        sent = 0
        for item in self.storage.due_outbox(self._clock()):
            try:
                self.client.send(item["text"], item["photo_path"])
            except TelegramError as exc:
                self._retry(item, exc)
                continue
            self.storage.mark_sent(item["id"])
            if item["incident_id"] is not None and item["kind"] == "fire":
                self.storage.update_incident(item["incident_id"], alert_sent=1)
            log.info("Telegram terkirim: %s #%d.", item["kind"], item["id"])
            self.storage.set_health("telegram", True, f"pesan terakhir terkirim {self._clock():%H:%M:%S}")
            sent += 1
        return sent

    def _retry(self, item: dict[str, Any], exc: TelegramError) -> None:
        attempts = item["attempts"] + 1
        give_up = exc.permanent or attempts >= MAX_ATTEMPTS
        delay = exc.retry_after if exc.retry_after is not None else BACKOFF_S[min(attempts - 1, len(BACKOFF_S) - 1)]
        self.storage.mark_retry(item["id"], str(exc), self._clock() + timedelta(seconds=delay), give_up)
        if give_up:
            log.error("Telegram gagal permanen untuk pesan #%d: %s", item["id"], exc)
        else:
            log.warning("Telegram gagal (#%d, percobaan %d), dicoba lagi %.0f dtk: %s", item["id"], attempts, delay, exc)
        self.storage.set_health("telegram", False, f"gagal: {exc}")

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.send_due()
            except Exception:
                log.exception("Pengiriman outbox gagal.")
            self._stop.wait(self.poll_s)
