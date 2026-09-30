from datetime import datetime

from extensions import db


class Attendance(db.Model):
    """Ek employee ki ek din mein ek hi row (check_in + last check_out)."""

    __tablename__ = "attendance"
    __table_args__ = (db.UniqueConstraint("employee_id", "date", name="uq_employee_date"),)

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(
        db.Integer, db.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    date = db.Column(db.Date, nullable=False, index=True)
    check_in = db.Column(db.DateTime, nullable=False)
    check_out = db.Column(db.DateTime)
    source_id = db.Column(db.String(50))
    similarity = db.Column(db.Float)