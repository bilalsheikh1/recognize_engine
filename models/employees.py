from datetime import datetime

from extensions import db


class Employee(db.Model):
    __tablename__ = "employees"

    id = db.Column(db.Integer, primary_key=True)
    emp_code = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    department = db.Column(db.String(120), default="")
    created_at = db.Column(db.DateTime, default=datetime.now)

    attendance = db.relationship(
        "Attendance", backref="employee", cascade="all, delete-orphan"
    )