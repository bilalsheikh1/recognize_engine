from datetime import datetime

from extensions import db



class SystemLog(db.Model):
    __tablename__ = "system_logs"

    id = db.Column(db.Integer, primary_key=True)
    level = db.Column(db.String(10), index=True)        # INFO / WARNING / ERROR
    category = db.Column(db.String(20), index=True)     # attendance / unknown / camera / register / system
    source = db.Column(db.String(50))
    message = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.now, index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "time": self.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "level": self.level,
            "category": self.category,
            "source": self.source,
            "message": self.message,
        }
