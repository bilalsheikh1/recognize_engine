import traceback

from flask import request
from flask_socketio import emit

from config.config import Config
from extensions import socketio, state
from logging_utils import log_db


class SocketController:
    def __init__(self):
        self.webcam_config = next(
            (c for c in Config.CAMERAS if c["type"] == "webcam"), None
        )

    def register_events(self):
        """SocketIO namespaces aur unke event handlers bind karna."""

        # ================================================================== /webcam namespace
        @socketio.on("connect", namespace="/webcam")
        def webcam_connect():
            if self.webcam_config is None:
                log_db(
                    "ERROR",
                    "system",
                    "webcam",
                    "CAMERAS array mein type='webcam' entry nahi hai",
                )
                return False

        @socketio.on("frame", namespace="/webcam")
        def on_frame(data):
            try:
                from app import FaceAttendanceApp

                data = data or {}
                frame = FaceAttendanceApp.decode_image(data.get("image"))

                if frame is None:
                    return {"ok": False, "error": "invalid frame"}

                # Frontend se aane wale zones aur camera id (zone-based attendance ke liye)
                db_zones = data.get("db_zones") or {}
                if not isinstance(db_zones, dict):
                    db_zones = {}
                camera_id = data.get("camera_id") or self.webcam_config["id"]

                faces = state.service.process(
                    frame,
                    self.webcam_config["id"],
                    self.webcam_config["name"],
                    db_zones=db_zones,
                    camera_id=camera_id,
                )
                return {"ok": True, "faces": faces}
            except Exception as exc:
                cam_id = (
                    self.webcam_config["id"] if self.webcam_config else "webcam"
                )
                log_db(
                    "ERROR",
                    "system",
                    cam_id,
                    f"Webcam frame error: {exc}\n{traceback.format_exc()}",
                    throttle=30,
                )
                return {"ok": False, "error": "server error"}

        @socketio.on("register", namespace="/webcam")
        def on_register(data):
            from app import FaceAttendanceApp

            data = data or {}
            if not FaceAttendanceApp.admin_ok(data.get("admin_key")):
                log_db(
                    "WARNING",
                    "register",
                    request.remote_addr,
                    "Register attempt: galat admin key",
                    throttle=10,
                )
                return {"ok": False, "message": "Admin key ghalat hai."}
            try:
                frames = [
                    FaceAttendanceApp.decode_image(x)
                    for x in (data.get("frames") or [])[:12]
                ]
                frames = [f for f in frames if f is not None]
                ok, msg = state.service.register_employee(
                    data.get("code"),
                    data.get("name"),
                    data.get("department"),
                    frames,
                )
            except Exception as exc:
                log_db(
                    "ERROR",
                    "system",
                    "register",
                    f"Register error: {exc}\n{traceback.format_exc()}",
                )
                return {"ok": False, "message": "Server error."}
            if ok:
                socketio.emit("employees_changed", {}, namespace="/webcam")
            return {"ok": ok, "message": msg}

        @socketio.on("list_employees", namespace="/webcam")
        def on_list_employees(_data=None):
            return {"ok": True, "employees": state.service.list_employees()}

        @socketio.on("delete_employee", namespace="/webcam")
        def on_delete_employee(data):
            from app import FaceAttendanceApp

            data = data or {}
            if not FaceAttendanceApp.admin_ok(data.get("admin_key")):
                return {"ok": False, "message": "Admin key ghalat hai."}
            ok, msg = state.service.delete_employee(data.get("id"))
            if ok:
                socketio.emit("employees_changed", {}, namespace="/webcam")
            return {"ok": ok, "message": msg}

        # ================================================================== /cctv + /events namespaces
        @socketio.on("connect", namespace="/cctv")
        def cctv_connect():
            if state.manager:
                emit("camera_list", state.manager.info())

        @socketio.on("connect", namespace="/events")
        def events_connect():
            pass

        # Global Socket Error Handler
        @socketio.on_error_default
        def on_socket_error(exc):
            ev = getattr(request, "event", {}).get("message", "?")
            log_db(
                "ERROR",
                "system",
                f"socket:{ev}",
                f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}",
                throttle=10,
            )


# Single instance create karke export karein
socket_controller = SocketController()