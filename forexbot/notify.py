"""Trade alerts via Telegram and/or email — stdlib only, no extra packages.

Configure in .env (all optional; unset channels are simply skipped):

    # Telegram: message @BotFather to create a bot + get a token, then get your chat id.
    TELEGRAM_BOT_TOKEN=123456:ABC...
    TELEGRAM_CHAT_ID=987654321

    # Email (SMTP, e.g. Gmail app password):
    SMTP_HOST=smtp.gmail.com
    SMTP_PORT=587
    SMTP_USER=you@gmail.com
    SMTP_PASSWORD=your-app-password
    ALERT_EMAIL_TO=you@gmail.com

A Notifier never raises into the trading loop — a failed alert is logged and swallowed,
so a Telegram outage can't stop the bot from trading.
"""

from __future__ import annotations

import logging
import smtplib
import urllib.parse
import urllib.request
from email.mime.text import MIMEText

from .config import env_int, env_str

log = logging.getLogger("forexbot.notify")


def send_telegram_to(chat_id: str, text: str) -> bool:
    """Send a message to a specific Telegram chat using the platform bot token.

    Uses the global TELEGRAM_BOT_TOKEN (your platform bot) with the given chat id, so it
    can message any customer. Used for password-reset codes. Never raises.
    """
    token = env_str("TELEGRAM_BOT_TOKEN", "")
    if not (token and chat_id):
        return False
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
        with urllib.request.urlopen(url, data=data, timeout=10) as resp:
            resp.read()
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("Telegram send failed: %s", exc)
        return False


class Notifier:
    def __init__(self) -> None:
        self.tg_token = env_str("TELEGRAM_BOT_TOKEN", "")
        self.tg_chat = env_str("TELEGRAM_CHAT_ID", "")
        self.smtp_host = env_str("SMTP_HOST", "")
        self.smtp_port = env_int("SMTP_PORT", 587)
        self.smtp_user = env_str("SMTP_USER", "")
        self.smtp_password = env_str("SMTP_PASSWORD", "")
        self.email_to = env_str("ALERT_EMAIL_TO", "")

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.tg_token and self.tg_chat)

    @property
    def email_enabled(self) -> bool:
        return bool(self.smtp_host and self.smtp_user and self.email_to)

    @property
    def any_enabled(self) -> bool:
        return self.telegram_enabled or self.email_enabled

    def send(self, message: str, subject: str = "forex-bot alert") -> None:
        """Best-effort fan-out to all configured channels. Never raises."""
        if self.telegram_enabled:
            self._send_telegram(message)
        if self.email_enabled:
            self._send_email(subject, message)

    # ── channels ─────────────────────────────────────────────────────────────
    def _send_telegram(self, message: str) -> None:
        try:
            url = f"https://api.telegram.org/bot{self.tg_token}/sendMessage"
            data = urllib.parse.urlencode(
                {"chat_id": self.tg_chat, "text": message}
            ).encode()
            with urllib.request.urlopen(url, data=data, timeout=10) as resp:
                resp.read()
        except Exception as exc:  # noqa: BLE001 — alerts must not break trading
            log.warning("Telegram alert failed: %s", exc)

    def _send_email(self, subject: str, message: str) -> None:
        try:
            msg = MIMEText(message)
            msg["Subject"] = subject
            msg["From"] = self.smtp_user
            msg["To"] = self.email_to
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=15) as s:
                s.starttls()
                s.login(self.smtp_user, self.smtp_password)
                s.send_message(msg)
        except Exception as exc:  # noqa: BLE001
            log.warning("Email alert failed: %s", exc)
