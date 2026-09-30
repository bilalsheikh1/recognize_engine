from datetime import datetime

from extensions import db


class UnknownFace(db.Model):
    """Har unknown banday ki ek row; seen_count = kitni baar (visits) aaya."""

    __tablename__ = "unknown_faces"

    id = db.Column(db.Integer, primary_key=True)
    label = db.Column(db.String(20), nullable=False, default="UNK")
    first_seen = db.Column(db.DateTime, default=datetime.now)
    last_seen = db.Column(db.DateTime, default=datetime.now)
    seen_count = db.Column(db.Integer, default=1)
    last_source = db.Column(db.String(50))
    snapshot = db.Column(db.String(255))