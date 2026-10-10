import hmac
import json
import math
import os
import traceback
import cv2
import numpy as np
from flask import jsonify, request
from config.config import Config
from logging_utils import log_db

from models import Camera
from models.zones import Zone
from extensions import db, socketio, state


class ZoneController:
    """CCTV Zones Management and Visualization Class."""

    def __init__(self, config_path=None):
        self.config_path = config_path or os.path.join(
            Config.STATIC_DIR, "zones_config.json"
        )
        self._last_mtime = 0
        self._zones_cache = {}
        self.cached_zones = {}

    def _reload_if_changed(self):
        """JSON file ki modification time check karke cache update karta hai."""
        if not os.path.exists(self.config_path):
            self._zones_cache = {}
            return

        try:
            mtime = os.path.getmtime(self.config_path)
            if mtime > self._last_mtime:
                with open(self.config_path, "r") as f:
                    self._zones_cache = json.load(f)
                self._last_mtime = mtime
        except Exception as e:
            print(f"Error loading zones config file: {e}")

    def _reload_from_db(self):
        """DB se saare zones fetch karke in-memory dictionary format mein cached rakhta hai."""
        try:
            all_zones = Zone.query.all()
            config_map = {}

            for z in all_zones:
                cam_id = str(z.camera_id)
                if cam_id not in config_map:
                    config_map[cam_id] = {}
                config_map[cam_id][z.zone_key] = z.polygon

            self.cached_zones = config_map
            return config_map
        except Exception as e:
            log_db("ERROR", "system", "zones", f"Error loading zones from DB: {e}")
            return {}

    @staticmethod
    def serialize_numpy(obj):
        """Recursively converts NumPy ndarrays, int/float types into standard Python types."""
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, (np.integer, int)):
            return int(obj)
        elif isinstance(obj, (np.floating, float)):
            return float(obj)
        elif isinstance(obj, dict):
            return {k: ZoneController.serialize_numpy(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [ZoneController.serialize_numpy(i) for i in obj]
        return obj

    def fetch_zones_from_db_or_file(self, camera_id=None):
        """DB se pehle aur fallback JSON file se zones fetch karta hai."""
        # 1. First try DB
        db_zones = self._reload_from_db()

        if db_zones:
            if camera_id:
                cam_key = str(camera_id)
                return db_zones.get(cam_key, {"door_zone": [], "exit_zone": []})
            return db_zones

        # 2. Fallback to JSON file if DB empty
        self._reload_if_changed()
        if not self._zones_cache:
            if camera_id:
                return {"door_zone": [], "exit_zone": []}
            return {}

        cleaned_data = self.serialize_numpy(self._zones_cache)
        if camera_id:
            cam_key = str(camera_id)
            return cleaned_data.get(
                cam_key,
                cleaned_data.get(camera_id, {"door_zone": [], "exit_zone": []}),
            )

        return cleaned_data

    def get_zones1(self, camera_id):
        """OpenCV rendering ke liye NumPy arrays return karta hai."""
        cam_zones = self.fetch_zones_from_db_or_file(camera_id)
        if not cam_zones:
            return None, None

        door_points = cam_zones.get("door_zone") or cam_zones.get("checkin") or []
        exit_points = cam_zones.get("exit_zone") or cam_zones.get("checkout") or []

        door_poly = np.array(door_points, np.int32) if len(door_points) > 0 else None
        exit_poly = np.array(exit_points, np.int32) if len(exit_points) > 0 else None

        return door_poly, exit_poly

    # ------------------------------------------------------------------ zone-based attendance ke liye
    @staticmethod
    def _segments_intersect(p1, p2, p3, p4):
        def side(a, b, c):
            return (c[0] - a[0]) * (b[1] - a[1]) - (b[0] - a[0]) * (c[1] - a[1])

        return (
            side(p1, p3, p4) * side(p2, p3, p4) < 0
            and side(p1, p2, p3) * side(p1, p2, p4) < 0
        )

    @classmethod
    def _is_self_intersecting(cls, pts):
        """Bowtie / hourglass polygon pakadta hai (koi do non-adjacent edges cross karein)."""
        n = len(pts)
        for i in range(n):
            for j in range(i + 1, n):
                if abs(i - j) == 1 or (i == 0 and j == n - 1):
                    continue
                if cls._segments_intersect(
                    pts[i], pts[(i + 1) % n], pts[j], pts[(j + 1) % n]
                ):
                    return True
        return False

    @classmethod
    def normalize_polygon(cls, raw):
        """[[x, y], ...] ya [{x, y}, ...] -> [[x, y], ...] (ints).

        Agar points bowtie order mein hain to unhe centroid ke angle se sort karta hai;
        theek polygon (concave bhi) jaisa hai waisa rehta hai. live.html bhi yehi karta hai,
        taake page pe dikhne wala zone aur backend ka zone same ho.
        """
        pts = []
        for p in raw or []:
            if isinstance(p, (list, tuple)) and len(p) >= 2:
                x, y = p[0], p[1]
            elif isinstance(p, dict) and "x" in p and "y" in p:
                x, y = p["x"], p["y"]
            else:
                continue
            try:
                pts.append([int(round(float(x))), int(round(float(y)))])
            except (TypeError, ValueError):
                continue

        if len(pts) >= 4 and cls._is_self_intersecting(pts):
            cx = sum(p[0] for p in pts) / len(pts)
            cy = sum(p[1] for p in pts) / len(pts)
            pts.sort(key=lambda p: math.atan2(p[1] - cy, p[0] - cx))
        return pts

    def get_zones(self, camera_id):
        """Flask API Route GET response generator."""
        zones = self.fetch_zones_from_db_or_file(camera_id)
        zones = self.serialize_numpy(zones)
        return jsonify({"ok": True, "camera_id": camera_id, "zones": zones})

    def draw_zones(self, frame, camera_id):
        """Frame par Door Zone (Green) aur Exit Zone (Red) overlays render karta hai."""
        door_poly, exit_poly = self.get_zones1(camera_id)

        # Door Zone (Green Overlay)
        if door_poly is not None and len(door_poly) > 2:
            cv2.polylines(frame, [door_poly], isClosed=True, color=(0, 255, 0), thickness=2)
            overlay = frame.copy()
            cv2.fillPoly(overlay, [door_poly], (0, 255, 0))
            cv2.addWeighted(overlay, 0.25, frame, 0.75, 0, frame)

        # Exit Zone (Red Overlay)
        if exit_poly is not None and len(exit_poly) > 2:
            cv2.polylines(frame, [exit_poly], isClosed=True, color=(0, 0, 255), thickness=2)
            overlay = frame.copy()
            cv2.fillPoly(overlay, [exit_poly], (0, 0, 255))
            cv2.addWeighted(overlay, 0.25, frame, 0.75, 0, frame)

        return frame

    def admin_ok(self, key):
        return hmac.compare_digest(
            str(key or "").encode(), Config.ADMIN_KEY.encode()
        )

    def save_zones(self):
        """Safely saves camera zones to DB handling both nested dicts and flat camera objects."""
        try:
            data = request.get_json() or {}
            admin_key = data.get("admin_key")

            if not self.admin_ok(admin_key):
                return {"ok": False, "message": "Admin key ghalat hai."}, 401

            target_camera_id = data.get("camera_id")
            zones_payload = data.get("zones", {})
            serialized_payload = self.serialize_numpy(zones_payload)

            # Normalization logic to build: { camera_id: { zone_key: points } }
            cameras_map = {}

            if isinstance(serialized_payload, dict):
                # Check if dictionary is directly zone types: {"door_zone": [...], "exit_zone": [...]}
                if "door_zone" in serialized_payload or "exit_zone" in serialized_payload:
                    if target_camera_id:
                        cameras_map[str(target_camera_id)] = serialized_payload
                    else:
                        return {"ok": False, "message": "Camera ID select nahi hua!"}, 400
                else:
                    # Dictionary contains nested camera IDs: {"cam1": {"door_zone": [...]}}
                    cameras_map = serialized_payload
            elif isinstance(serialized_payload, list) and target_camera_id:
                # If array of zone objects passed
                cam_zones = {}
                for item in serialized_payload:
                    if isinstance(item, dict):
                        z_key = item.get("id") or item.get("type") or "door_zone"
                        pts = item.get("polygon") or item.get("points") or []
                        cam_zones[z_key] = pts
                cameras_map[str(target_camera_id)] = cam_zones

            # DB Save Loop
            for camera_id, camera_zones in cameras_map.items():
                cam_id_str = str(camera_id)

                if not isinstance(camera_zones, dict):
                    continue

                # 1. Foreign Key Constraint satisfy karne ke liye camera record ensure karein
                cam_record = Camera.query.filter_by(id=cam_id_str).first()
                if not cam_record:
                    cam_record = Camera(
                        id=cam_id_str,
                        name=f"Camera {cam_id_str}",
                        type="webcam" if "webcam" in cam_id_str.lower() else "cctv"
                    )
                    db.session.add(cam_record)
                    db.session.flush()

                # 2. Zones Insert / Update
                for zone_key, points in camera_zones.items():
                    if not isinstance(points, list):
                        continue

                    zone_record = Zone.query.filter_by(
                        camera_id=cam_id_str,
                        zone_key=str(zone_key)
                    ).first()

                    z_type = "checkin" if any(k in str(zone_key).lower() for k in ["in", "entry", "door"]) else "checkout"
                    z_name = str(zone_key).replace("_", " ").title()

                    if zone_record:
                        zone_record.polygon = points
                        zone_record.name = z_name
                        zone_record.type = z_type
                    else:
                        new_zone = Zone(
                            camera_id=cam_id_str,
                            zone_key=str(zone_key),
                            name=z_name,
                            type=z_type,
                            polygon=points
                        )
                        db.session.add(new_zone)

            db.session.commit()
            self._reload_from_db()

            log_db("INFO", "system", "zones", "Zones successfully updated in DB")
            return {
                "ok": True,
                "message": "Zones successfully DB mein save ho gaye hain!",
            }, 200

        except Exception as exc:
            db.session.rollback()
            log_db("ERROR", "system", "zones", f"Zone save error: {exc}\n{traceback.format_exc()}")
            return {
                "ok": False,
                "message": f"Server error while saving zones: {str(exc)}",
            }, 500

# Single instance export
zone_controller = ZoneController()