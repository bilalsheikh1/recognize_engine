from extensions import db
from .attendance import Attendance
from .employees import Employee
from .unknown_face import UnknownFace
from .system_logs import SystemLog
from models.user import User

# Taake app.py mein sirf "from models import User, Post" likhna pare
__all__ = ['Attendance', 'Employee', 'UnknownFace', 'SystemLog']
