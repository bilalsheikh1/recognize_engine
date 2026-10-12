"""
Face Attendance — Flask + Flask-SocketIO (threading) + InsightFace + ChromaDB + MySQL.

Sockets (namespaces):
  /webcam  browser webcam: frame (attendance), register, list_employees, delete_employee
  /cctv    server -> browser: cctv_frame, camera_status, camera_list   (CCTV threads push karte hain)
  /events  server -> browser: new_log (live logs)
Attendance sirf socket se lagti hai — koi REST endpoint nahi.
"""
from config.config import Config  # sabse pehle: cv2 se pehle env vars set hotay hain
import os
os.environ["OMP_NUM_THREADS"] = "1"
import faulthandler; faulthandler.enable()
import base64
import hmac
import logging
import os
from datetime import date, datetime
import cv2
import numpy as np
import pymysql
from flask import Flask, render_template, request
from sqlalchemy.orm import joinedload

# Extension Instances
from extensions import db, socketio, state
from logging_utils import log_db, setup_file_logging
from models import Attendance, SystemLog, UnknownFace  # noqa: F401  (tables register hone ke liye)
from controllers.socket.socket_controller import socket_controller
from routes.web import web_bp
from routes.api import api_bp
# Services and AI Engines
from service.attendance_service import AttendanceService
from action.camera.camera_manager import CameraManager
from action.ai.face.face_engine import FaceEngine
from v_db.vector_store import VectorStore
from models.camera import Camera


class FaceAttendanceApp:
    def __init__(self):
        self.app = Flask(__name__)
        self.app.config.from_object(Config)
        self.webcam_config = next((c for c in Config.CAMERAS if c["type"] == "webcam"), None)

        # 1. First ensure database exists on MySQL server
        self._ensure_database()

        # 2. Setup Flask extensions & Application state in correct order
        self._init_extensions()
        self._setup_environment()

        # 3. Register Blueprints and Routes AFTER app context and extensions are fully ready
        self._register_routes()
        socket_controller.register_events()
        # self._register_socket_events()

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
        # Step A: Bind DB & SocketIO with App Instance
        db.init_app(self.app)
        socketio.init_app(
            self.app,
            async_mode="threading",
            cors_allowed_origins=Config.CORS_ORIGINS,
            max_http_buffer_size=10 * 1024 * 1024,  # registration ke 6 HD frames ke liye
        )

        state.app = self.app
        setup_file_logging()

        # Step B: Execute DB Operations & Load Cache WITHIN App Context
        with self.app.app_context():
            db.create_all()

            # Business logic engines aur managers initialization
            state.engine = FaceEngine()
            state.store = VectorStore()

            # Yahan Employee.query.all() safely execute ho jaye ga
            state.service = AttendanceService(self.app, state.engine, state.store)
            camera = Camera().query.all()
            print(" camera query data: ")
            print(camera)

            # Config.CAMERAS
            state.manager = CameraManager(camera, state.service)

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

        self.app.register_blueprint(web_bp)
        self.app.register_blueprint(api_bp)

        @self.app.route("/register")
        def register_page():
            return render_template("register.html", webcam=self.webcam_config)

        @self.app.route("/zones")
        def zones_page():
            return render_template("zones.html", cameras=self.manager.info(), webcam=self.webcam_config)

        @self.app.route("/camera")
        def camera_page():
            return render_template("cameras.html", cameras=self.manager.info(), webcam=self.webcam_config)

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

    def run(self):
        """Application aur background camera manager ko start karna."""
        self.manager.start()  # CCTV threads start
        log_db("INFO", "system", "app", f"Server ready — {len(Config.CAMERAS)} camera(s) in array")

        kwargs = {}
        if Config.SSL_CERT and Config.SSL_KEY:
            kwargs["ssl_context"] = (Config.SSL_CERT, Config.SSL_KEY)

        # use_reloader=False zaroori hai warna model + camera threads do baar start ho jate hain
        # socketio.run(
        #     self.app,
        #     host=Config.HOST,
        #     port=Config.PORT,
        #     debug=True,
        #     use_reloader=False,
        #     **kwargs
        # )

        socketio.run(
            self.app,
            host='0.0.0.0',
            port=5000,
            debug=True,
            use_reloader=False,
            allow_unsafe_werkzeug=True,
            log_output=False
        )


def main():
    face_app = FaceAttendanceApp()
    face_app.run()


if __name__ == '__main__':
    main()