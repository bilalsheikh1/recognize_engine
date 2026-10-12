from datetime import datetime

from extensions import db


class Zone(db.Model):
    __tablename__ = 'zones'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    camera_id = db.Column(db.String(50), db.ForeignKey('cameras.id'), nullable=False)

    zone_key = db.Column(db.String(50), nullable=False)  # e.g., 'door_zone', 'exit_zone', 'zone_in'
    name = db.Column(db.String(100), nullable=False)  # e.g., 'Entrance Area'
    type = db.Column(db.String(20), nullable=False)  # 'checkin' ya 'checkout'

    # Polygon Coordinates ko JSON field mein store karein: [[x1, y1], [x2, y2], ...]
    polygon = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "camera_id": self.camera_id,
            "zone_key": self.zone_key,
            "name": self.name,
            "type": self.type,
            "polygon": self.polygon
        }