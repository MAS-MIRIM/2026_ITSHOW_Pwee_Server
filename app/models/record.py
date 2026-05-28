from datetime import datetime, timezone
from app.models.db import db


class SoloRecord(db.Model):
    __tablename__ = "solo_records"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    clear_time_ms = db.Column(db.Integer, nullable=False)
    expression_count = db.Column(db.Integer, nullable=False, default=10)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user = db.relationship("User", back_populates="solo_records")

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "username": self.user.username if self.user else None,
            "clear_time_ms": self.clear_time_ms,
            "clear_time_sec": round(self.clear_time_ms / 1000, 2),
            "created_at": self.created_at.isoformat(),
        }
