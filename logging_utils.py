import logging
import os
import threading
import time
from logging.handlers import RotatingFileHandler

from config.config import Config
from extensions import db, socketio, state
from models import SystemLog

_throttle = {}
_throttle_lock = threading.Lock()


def setup_file_logging():
    os.makedirs(Config.LOG_DIR, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")

    fh = RotatingFileHandler(
        os.path.join(Config.LOG_DIR, "app.log"), maxBytes=5_000_000, backupCount=5, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers = [fh, sh]
    for noisy in ("werkzeug", "engineio", "socketio", "chromadb", "httpx", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def log_db(level, category, source, message, throttle=0):
    """File + MySQL mein log likhta hai aur /events socket par live push karta hai.

    throttle=N seconds: same message N seconds mein dobara nahi likhega (error flood se bachne ke liye).
    Ye function kabhi exception nahi phenkta — DB down ho to bhi file log mein entry rehti hai.
    """
    level = level.upper()
    if throttle:
        key = (category, str(source), message[:80])
        now = time.time()
        with _throttle_lock:
            if now - _throttle.get(key, 0) < throttle:
                return
            _throttle[key] = now

    logging.getLogger(category).log(getattr(logging, level, logging.INFO), "[%s] %s", source, message)

    try:
        with state.app.app_context():
            row = SystemLog(level=level, category=category, source=str(source)[:50], message=message)
            db.session.add(row)
            db.session.commit()
            payload = row.to_dict()
        socketio.emit("new_log", payload, namespace="/events")
    except Exception:
        logging.getLogger("logdb").exception("DB mein log save nahi ho saka (file log mein maujood hai)")
