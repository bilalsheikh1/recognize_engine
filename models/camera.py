from extensions import db
from datetime import datetime

class Camera(db.Model):
    __tablename__ = 'cameras'

    id = db.Column(db.String(50), primary_key=True)  # e.g., 'webcam-1', 'cctv-01'
    name = db.Column(db.String(100), nullable=False)
    type = db.Column(db.String(20), nullable=False, default='webcam') # 'webcam' ya 'cctv'
    source = db.Column(db.String(255), nullable=True) # RTSP URL ya device index
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # One-to-Many Relationship: Camera delete hone par uske sare zones b delete ho jayenge (cascade)
    zones = db.relationship('Zone', backref='camera', cascade='all, delete-orphan', lazy=True)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "source": self.source,
            "is_active": self.is_active,
            "zones": [zone.to_dict() for zone in self.zones]
        }