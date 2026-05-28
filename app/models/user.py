from datetime import datetime, timezone
from app.models.db import db


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    solo_records = db.relationship("SoloRecord", back_populates="user", lazy="dynamic")

    def to_dict(self):
        return {"id": self.id, "username": self.username}
