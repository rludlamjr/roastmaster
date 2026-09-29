"""Email a roast report (optional).

Configured by a small TOML file, by default ``~/.config/roastmaster/email.toml``::

    smtp_host = "smtp.gmail.com"
    smtp_port = 465              # 465 = SSL, 587 = STARTTLS
    username  = "you@gmail.com"
    password  = "abcd efgh ijkl mnop"   # a Gmail *app password*, not your login
    to        = "you@gmail.com"
    auto_send = true             # email automatically when a roast is finalized

If the file is missing, email is simply disabled.
"""

from __future__ import annotations

import json
import logging
import smtplib
import ssl
import threading
import tomllib
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path

from roastmaster.engine.analysis import fmt_time
from roastmaster.export.report import html_report, samples_csv, text_summary
from roastmaster.profiles.schema import RoastProfile

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "roastmaster" / "email.toml"


@dataclass
class EmailConfig:
    smtp_host: str
    smtp_port: int
    username: str
    password: str
    to: str
    sender: str = ""
    auto_send: bool = True

    @classmethod
    def load(cls, path: Path | None = None) -> EmailConfig | None:
        path = path or DEFAULT_CONFIG_PATH
        if not path.is_file():
            return None
        try:
            d = tomllib.loads(path.read_text())
            return cls(
                smtp_host=str(d["smtp_host"]),
                smtp_port=int(d.get("smtp_port", 465)),
                username=str(d["username"]),
                password=str(d["password"]),
                to=str(d["to"]),
                sender=str(d.get("from", d["username"])),
                auto_send=bool(d.get("auto_send", True)),
            )
        except (OSError, KeyError, ValueError, tomllib.TOMLDecodeError) as exc:
            logger.warning("Email config %s unusable: %s", path, exc)
            return None


def build_message(profile: RoastProfile, cfg: EmailConfig) -> EmailMessage:
    a = profile.analyze()
    parts = [f"Roast {profile.roast_date}"]
    if profile.coffee:
        parts.append(profile.coffee)
    if a.charged:
        stats = fmt_time(a.end_s)
        if a.dtr_pct is not None:
            stats += f" DTR {a.dtr_pct:.1f}%"
        parts.append(stats)
    msg = EmailMessage()
    msg["Subject"] = " | ".join(parts)
    msg["From"] = cfg.sender or cfg.username
    msg["To"] = cfg.to
    msg.set_content(text_summary(profile, a))
    stem = profile.roast_id or "roast"
    msg.add_attachment(html_report(profile, a).encode(), maintype="text", subtype="html",
                       filename=f"{stem}.html")
    msg.add_attachment(samples_csv(profile).encode(), maintype="text", subtype="csv",
                       filename=f"{stem}_samples.csv")
    msg.add_attachment(json.dumps(profile.to_dict(), indent=1).encode(),
                       maintype="application", subtype="json", filename=f"{stem}.json")
    return msg


def send_roast(profile: RoastProfile, cfg: EmailConfig, *, timeout: float = 20.0) -> None:
    """Send the report. Raises on failure."""
    msg = build_message(profile, cfg)
    ctx = ssl.create_default_context()
    if cfg.smtp_port == 465:
        with smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port, context=ctx, timeout=timeout) as s:
            s.login(cfg.username, cfg.password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=timeout) as s:
            s.starttls(context=ctx)
            s.login(cfg.username, cfg.password)
            s.send_message(msg)
    logger.info("Emailed roast %s to %s", profile.roast_id, cfg.to)


def send_roast_async(profile: RoastProfile, cfg: EmailConfig, on_done=None) -> threading.Thread:
    """Send in a background thread; ``on_done(ok: bool, error: str)`` is called after."""

    def run() -> None:
        try:
            send_roast(profile, cfg)
        except Exception as exc:  # noqa: BLE001 — report any failure to the UI
            logger.warning("Email failed for %s: %s", profile.roast_id, exc)
            if on_done:
                on_done(False, str(exc))
            return
        if on_done:
            on_done(True, "")

    t = threading.Thread(target=run, name="roast-email", daemon=True)
    t.start()
    return t
