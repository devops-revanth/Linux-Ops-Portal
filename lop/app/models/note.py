"""
Note model.

Free-text notes attached to a Server.  Multiple notes per server are
supported and are ordered newest-first.  Notes are manually entered only
— Ansible does not touch this table.
"""
from datetime import datetime, timezone

from ..extensions import db


class Note(db.Model):
    __tablename__ = "notes"

    id: int = db.Column(db.Integer, primary_key=True)
    server_id: int = db.Column(
        db.Integer,
        db.ForeignKey("linux_servers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    author: str = db.Column(db.String(150), nullable=True)   # Username or display name
    body: str = db.Column(db.Text, nullable=False)
    created_at: datetime = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: datetime = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationship
    server = db.relationship("Server", back_populates="notes")

    def __repr__(self) -> str:
        return f"<Note id={self.id} server={self.server_id}>"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "server_id": self.server_id,
            "author": self.author,
            "body": self.body,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
