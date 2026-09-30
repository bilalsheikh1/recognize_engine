"""Face Attendance — Flask + Flask-SocketIO (threading) + InsightFace + ChromaDB + MySQL.

Sockets (namespaces):
  /webcam  browser webcam: frame (attendance), register, list_employees, delete_employee
  /cctv    server -> browser: cctv_frame, camera_status, camera_list   (CCTV threads push karte hain)
  /events  server -> browser: new_log (live logs)
Attendance sirf socket se lagti hai — koi REST endpoint nahi.
"""
from config.config import Config  # sabse pehle: cv2 se pehle env vars set hotay hain

import base64
import hmac
import logging
import os
import traceback
from datetime import date, datetime

import cv2
import numpy as np
import pymysql
from flask import Flask, render_template, request
from flask_socketio import emit
from sqlalchemy.orm import joinedload

from service.attendance_service import AttendanceService
from action.camera.camera_manager import CameraManager
from extensions import db, socketio, state
from action.ai.face.face_engine import FaceEngine
from logging_utils import log_db, setup_file_logging
from v_db.vector_store import VectorStore

from models import Attendance, SystemLog, UnknownFace  # noqa: F401  (tables register hone ke liye)

class FaceAttendanceApp:
    def __init__(self):
        self.app = Flask(__name__)
        self.app.config.from_object(Config)
        self.webcam_config = next((c for c in Config.CAMERAS if c["type"] == "webcam"), None)

        # Application setup steps
        self._ensure_database()
        self._init_extensions()
        self._setup_environment()
        self._register_routes()
        self._register_socket_events()

    def _ensure_database(self):
        """Database na ho to bana do."""
        conn = pymysql.connect(
            host=Config.DB_HOST, port=Config.DB_PORT, user=Config.DB_USER, password=Config.DB_PASSWORD
        )
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"CREATE DATABASE IF NOT EXISTS `{Config.DB_NAME}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
            conn.commit()
        finally:
            conn.close()

    def _init_extensions(self):
        """Flask extensions aur application state ko initialize karna."""
        db.init_app(self.app)
        socketio.init_app(
            self.app,
            async_mode="threading",
            cors_allowed_origins=Config.CORS_ORIGINS,
            max_http_buffer_size=10 * 1024 * 1024,  # registration ke 6 HD frames ke liye
        )

        state.app = self.app
        setup_file_logging()

        with self.app.app_context():
            db.create_all()

        # Business logic engines aur managers initialization
        state.engine = FaceEngine()
        state.store = VectorStore()
        state.service = AttendanceService(self.app, state.engine, state.store)
        state.manager = CameraManager(Config.CAMERAS, state.service)

        # Class attributes me reference save karna short syntax k liye
        self.service = state.service
        self.manager = state.manager

        if Config.ADMIN_KEY == "admin123":
            logging.getLogger("system").warning("ADMIN_KEY default hai — .env mein badal dein!")

    def _setup_environment(self):
        """Zaroori directories setup karna."""
        os.makedirs(os.path.join(Config.STATIC_DIR, "unknowns"), exist_ok=True)

    @staticmethod
    def decode_image(data_url):
        if not data_url:
            return None
        b64 = data_url.split(",", 1)[1] if "," in data_url else data_url
        arr = np.frombuffer(base64.b64decode(b64), np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)

    @staticmethod
    def admin_ok(key):
        return hmac.compare_digest(str(key or "").encode(), Config.ADMIN_KEY.encode())

    def _register_routes(self):
        """HTML pages ke routes register karna."""

        @self.app.route("/")
        def live_page():
            return render_template("live.html", cameras=self.manager.info(), webcam=self.webcam_config)

        @self.app.route("/register")
        def register_page():
            return render_template("register.html", webcam=self.webcam_config)

        @self.app.route("/logs")
        def logs_page():
            tab = request.args.get("tab", "system")
            category = request.args.get("category", "")
            level = request.args.get("level", "")
            day = request.args.get("date") or date.today().isoformat()
            rows = []

            if tab == "attendance":
                try:
                    d = datetime.strptime(day, "%Y-%m-%d").date()
                except ValueError:
                    d = date.today()
                rows = (
                    Attendance.query.options(joinedload(Attendance.employee))
                    .filter(Attendance.date == d)
                    .order_by(Attendance.check_in.desc())
                    .limit(500)
                    .all()
                )
            elif tab == "unknown":
                rows = UnknownFace.query.order_by(UnknownFace.last_seen.desc()).limit(500).all()
            else:
                tab = "system"
                q = SystemLog.query
                if category:
                    q = q.filter_by(category=category)
                if level:
                    q = q.filter_by(level=level)
                rows = q.order_by(SystemLog.id.desc()).limit(500).all()

            return render_template("logs.html", tab=tab, rows=rows, category=category, level=level, day=day)

    def _register_socket_events(self):
        """SocketIO namespaces aur unke events bind karna."""

        # ================================================================== /webcam namespace
        @socketio.on("connect", namespace="/webcam")
        def webcam_connect():
            if self.webcam_config is None:
                log_db("ERROR", "system", "webcam", "CAMERAS array mein type='webcam' entry nahi hai")
                return False

        @socketio.on("frame", namespace="/webcam")
        def on_frame(data):
            try:
                frame = self.decode_image((data or {}).get("image"))
                if frame is None:
                    return {"ok": False, "error": "invalid frame"}
                faces = self.service.process(frame, self.webcam_config["id"], self.webcam_config["name"])
                return {"ok": True, "faces": faces}
            except Exception as exc:
                log_db("ERROR", "system", self.webcam_config["id"], f"Webcam frame error: {exc}\n{traceback.format_exc()}", throttle=30)
                return {"ok": False, "error": "server error"}

        @socketio.on("register", namespace="/webcam")
        def on_register(data):
            data = data or {}
            if not self.admin_ok(data.get("admin_key")):
                log_db("WARNING", "register", request.remote_addr, "Register attempt: galat admin key", throttle=10)
                return {"ok": False, "message": "Admin key ghalat hai."}
            try:
                frames = [self.decode_image(x) for x in (data.get("frames") or [])[:12]]
                frames = [f for f in frames if f is not None]
                ok, msg = self.service.register_employee(data.get("code"), data.get("name"), data.get("department"), frames)
            except Exception as exc:
                log_db("ERROR", "system", "register", f"Register error: {exc}\n{traceback.format_exc()}")
                return {"ok": False, "message": "Server error."}
            if ok:
                socketio.emit("employees_changed", {}, namespace="/webcam")
            return {"ok": ok, "message": msg}

        @socketio.on("list_employees", namespace="/webcam")
        def on_list_employees(_data=None):
            return {"ok": True, "employees": self.service.list_employees()}

        @socketio.on("delete_employee", namespace="/webcam")
        def on_delete_employee(data):
            data = data or {}
            if not self.admin_ok(data.get("admin_key")):
                return {"ok": False, "message": "Admin key ghalat hai."}
            ok, msg = self.service.delete_employee(data.get("id"))
            if ok:
                socketio.emit("employees_changed", {}, namespace="/webcam")
            return {"ok": ok, "message": msg}

        # ================================================================== /cctv + /events namespaces
        @socketio.on("connect", namespace="/cctv")
        def cctv_connect():
            emit("camera_list", self.manager.info())

        @socketio.on("connect", namespace="/events")
        def events_connect():
            pass

        # Global Socket Error Handler
        @socketio.on_error_default
        def on_socket_error(exc):
            ev = getattr(request, "event", {}).get("message", "?")
            log_db("ERROR", "system", f"socket:{ev}", f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}", throttle=10)

    def run(self):
        """Application aur background camera manager ko start karna."""
        self.manager.start()  # CCTV threads start
        log_db("INFO", "system", "app", f"Server ready — {len(Config.CAMERAS)} camera(s) in array")

        kwargs = {}
        if Config.SSL_CERT and Config.SSL_KEY:
            kwargs["ssl_context"] = (Config.SSL_CERT, Config.SSL_KEY)

        # use_reloader=False zaroori hai warna model + camera threads do baar start ho jate hain
        socketio.run(
            self.app,
            host=Config.HOST,
            port=Config.PORT,
            debug=True,
            use_reloader=False,
            **kwargs
        )


def main():
    face_app = FaceAttendanceApp()
    face_app.run()


if __name__ == '__main__':
    main()
