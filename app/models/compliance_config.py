"""
Compliance configuration — singleton table for patch compliance thresholds.

Administrators configure:
  compliance_window_days  — servers patched within this window are Compliant (default 90)
  due_soon_days           — buffer before the window where status is Due Soon (default 15)

Example with defaults:
  0–90 days since last patch  → Compliant
  91–105 days                 → Due Soon
  106+ days (or never)        → Overdue
"""
from datetime import datetime, timezone

from ..extensions import db


class ComplianceConfig(db.Model):
    __tablename__ = "compliance_config"

    id: int = db.Column(db.Integer, primary_key=True)
    compliance_window_days: int = db.Column(
        db.Integer, nullable=False, default=90,
        comment="Days since last patch before status becomes Due Soon",
    )
    due_soon_days: int = db.Column(
        db.Integer, nullable=False, default=15,
        comment="Additional days after compliance_window before status becomes Overdue",
    )
    updated_at: datetime = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    @classmethod
    def get(cls) -> "ComplianceConfig":
        """Get (or create with defaults) the singleton config record."""
        cfg = cls.query.first()
        if cfg is None:
            cfg = cls(compliance_window_days=90, due_soon_days=15)
            db.session.add(cfg)
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
                cfg = cls.query.first() or cls(compliance_window_days=90, due_soon_days=15)
        return cfg

    def __repr__(self) -> str:
        return (
            f"<ComplianceConfig window={self.compliance_window_days}d "
            f"due_soon={self.due_soon_days}d>"
        )
