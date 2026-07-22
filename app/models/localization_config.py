"""
Regional Settings — singleton table for display timezone, date format, and
time format.  All timestamps are stored in UTC; these settings control how
they are rendered across the application.
"""
from datetime import datetime, timezone

from ..extensions import db


# ── Timezone choices ────────────────────────────────────────────────────────── #

TIMEZONE_CHOICES: list[str] = [
    "UTC",
    # North America
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "America/Phoenix",
    "America/Anchorage",
    "America/Honolulu",
    "America/Toronto",
    "America/Vancouver",
    "America/Mexico_City",
    "America/Sao_Paulo",
    "America/Argentina/Buenos_Aires",
    # Europe
    "Europe/London",
    "Europe/Dublin",
    "Europe/Paris",
    "Europe/Berlin",
    "Europe/Amsterdam",
    "Europe/Madrid",
    "Europe/Rome",
    "Europe/Stockholm",
    "Europe/Warsaw",
    "Europe/Helsinki",
    "Europe/Athens",
    "Europe/Moscow",
    # Middle East & Africa
    "Africa/Cairo",
    "Africa/Johannesburg",
    "Africa/Lagos",
    "Asia/Dubai",
    "Asia/Riyadh",
    # Asia
    "Asia/Kolkata",
    "Asia/Dhaka",
    "Asia/Colombo",
    "Asia/Bangkok",
    "Asia/Ho_Chi_Minh",
    "Asia/Jakarta",
    "Asia/Singapore",
    "Asia/Kuala_Lumpur",
    "Asia/Shanghai",
    "Asia/Hong_Kong",
    "Asia/Taipei",
    "Asia/Tokyo",
    "Asia/Seoul",
    # Australia & Pacific
    "Australia/Perth",
    "Australia/Darwin",
    "Australia/Brisbane",
    "Australia/Adelaide",
    "Australia/Sydney",
    "Australia/Melbourne",
    "Pacific/Auckland",
    "Pacific/Fiji",
]


# ── Date format choices ─────────────────────────────────────────────────────── #
# Each entry: (db_value, label, strftime_pattern)

DATE_FORMAT_CHOICES: list[tuple[str, str, str]] = [
    ("MMM_DD_YYYY", "Jul 21, 2026",  "%b %d, %Y"),
    ("DD_MM_YYYY",  "21/07/2026",    "%d/%m/%Y"),
    ("MM_DD_YYYY",  "07/21/2026",    "%m/%d/%Y"),
    ("YYYY_MM_DD",  "2026-07-21",    "%Y-%m-%d"),
]

DATE_FORMAT_STRFTIME: dict[str, str] = {v: p for v, _, p in DATE_FORMAT_CHOICES}


# ── Time format choices ─────────────────────────────────────────────────────── #
# Each entry: (db_value, label, strftime_pattern)

TIME_FORMAT_CHOICES: list[tuple[str, str, str]] = [
    ("12", "12-hour  (08:55 AM)", "%I:%M %p"),
    ("24", "24-hour  (20:55)",    "%H:%M"),
]

TIME_FORMAT_STRFTIME: dict[str, str] = {v: p for v, _, p in TIME_FORMAT_CHOICES}


# ── Model ───────────────────────────────────────────────────────────────────── #

class LocalizationConfig(db.Model):
    __tablename__ = "localization_config"

    id: int = db.Column(db.Integer, primary_key=True)

    timezone: str = db.Column(
        db.String(64),
        nullable=False,
        default="UTC",
        comment="IANA timezone name for display (e.g. America/Chicago)",
    )
    date_format: str = db.Column(
        db.String(20),
        nullable=False,
        default="MMM_DD_YYYY",
        comment="Date display format key (MMM_DD_YYYY | DD_MM_YYYY | MM_DD_YYYY | YYYY_MM_DD)",
    )
    time_format: str = db.Column(
        db.String(2),
        nullable=False,
        default="12",
        comment="Time display format key (12 | 24)",
    )
    updated_at: datetime = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    @classmethod
    def get(cls) -> "LocalizationConfig":
        """Return (or create with defaults) the singleton config record."""
        cfg = cls.query.first()
        if cfg is None:
            cfg = cls(timezone="UTC", date_format="MMM_DD_YYYY", time_format="12")
            db.session.add(cfg)
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
                cfg = cls.query.first() or cls(
                    timezone="UTC", date_format="MMM_DD_YYYY", time_format="12"
                )
        return cfg

    def __repr__(self) -> str:
        return (
            f"<LocalizationConfig timezone={self.timezone!r} "
            f"date={self.date_format!r} time={self.time_format!r}>"
        )
