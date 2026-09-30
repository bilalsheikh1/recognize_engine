from flask_socketio import SocketIO
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
socketio = SocketIO()


class _State:
    """Threads ko app/service tak pohanchane ke liye simple holder (circular import se bachne ke liye)."""

    app = None
    engine = None
    store = None
    service = None
    manager = None


state = _State()
