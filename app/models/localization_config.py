"""
Localization configuration — singleton table for display timezone.

All timestamps are stored in UTC. This setting controls the timezone
used when displaying timestamps across the application.
"""
from datetime import datetime, timezone

from ..extensions import db


# Comprehensive list of IANA timezone names available in the Settings UI.
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


class LocalizationConfig(db.Model):
    __tablename__ = "localization_config"

    id: int = db.Column(db.Integer, primary_key=True)
    timezone: str = db.Column(
        db.String(64),
        nullable=False,
        default="UTC",
        comment="IANA timezone name for display (e.g. America/Chicago)",
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
            cfg = cls(timezone="UTC")
            db.session.add(cfg)
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
                cfg = cls.query.first() or cls(timezone="UTC")
        return cfg

    def __repr__(self) -> str:
        return f"<LocalizationConfig timezone={self.timezone!r}>"
