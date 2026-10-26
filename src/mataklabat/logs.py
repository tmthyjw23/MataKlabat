"""Logging: short console lines plus rotating JSON-lines files (Spec §12).

A filter masks secrets (Telegram token, LLM API key) wherever they would appear.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
from pathlib import Path

from mataklabat.config import Settings

CONSOLE_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
MAX_BYTES = 5 * 1024 * 1024
BACKUPS = 5


class SecretFilter(logging.Filter):
    def __init__(self, secrets: list[str]):
        super().__init__()
        self.secrets = [s for s in secrets if s and len(s) >= 6]

    def filter(self, record: logging.LogRecord) -> bool:
        if self.secrets:
            message = record.getMessage()
            masked = message
            for secret in self.secrets:
                masked = masked.replace(secret, "***")
            if masked != message:
                record.msg, record.args = masked, ()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "thread": record.threadName,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data, ensure_ascii=False)


def setup_logging(settings: Settings | None, process: str, verbose: bool = False) -> None:
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    secrets = [] if settings is None else [settings.telegram_bot_token or "", settings.llm_api_key or ""]
    secret_filter = SecretFilter(secrets)

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(CONSOLE_FORMAT, datefmt="%H:%M:%S"))
    console.addFilter(secret_filter)
    root.addHandler(console)

    if settings is not None:
        log_dir = Path(settings.runtime_dir) / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_dir / f"{process}.log", maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8"
        )
        file_handler.setFormatter(JsonFormatter())
        file_handler.addFilter(secret_filter)
        root.addHandler(file_handler)

    # Third-party HTTP clients log full request URLs, which contain the Telegram token.
    for noisy in ("httpx", "httpcore", "urllib3", "openai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
