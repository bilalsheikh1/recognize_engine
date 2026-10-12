"""Core logic: recognise -> attendance / unknown tracking / registration.
CCTV threads aur webcam socket dono yahi service use karte hain."""

from collections import Counter
from datetime import datetime
import os
import re
import threading
import time

import cv2
from config.config import Config
from extensions import db, socketio  # socketio emit ke liye import kiya
from logging_utils import log_db
from models import Attendance, Employee, UnknownFace
import numpy as np

_CODE_RE = re.compile(r"^[A-Za-z0-9_\-]{1,50}$")

# new_attendance_event in namespaces pe emit hoga (live.html /webcam pe sunta hai)
_EVENT_NAMESPACES = ("/webcam", "/events")


class AttendanceService:

    def __init__(self, app, engine, store):
        self.app = app
        self.engine = engine
        self.store = store
        self._lock = threading.RLock()
        self._streaks = {}  # (source_id, emp_id) -> (count, last_ts)
        self._last_marked = {}  # emp_id -> ts
        self._unknown_seen = {}  # unknown_id -> ts (last dekha gaya)
        self._emp_cache = {}  # emp_id -> {"name", "code"}
        self._last_zone_event = ({})  # emp_id -> {"last_event": 'check_in'/'check_out', "time": datetime}
        self.reload_cache()

    def reload_cache(self):
        with self.app.app_context():
            self._emp_cache = {
                e.id: {"name": e.name, "code": e.emp_code}
                for e in Employee.query.all()
            }

    # ------------------------------------------------------------------ recognition
    def process(
        self, frame, source_id, source_name="", db_zones=None, camera_id=None
    ):
        """Ek frame process karo."""
        results = []
        detected_faces_for_zone = []

        for face in self.engine.detect(frame):
            emb = face.normed_embedding
            box = [int(v) for v in face.bbox]
            emp_id, sim = self.store.search_employee(emb)
            info = (
                self._emp_cache.get(emp_id) if emp_id is not None else None
            )
            item = {"box": box, "sim": round(float(sim), 3)}

            if info and sim >= Config.MATCH_THRESHOLD:
                status = self._on_known(
                    emp_id, info, sim, source_id, source_name
                )
                # int() zaroori hai: vector DB numpy int de sakta hai jo
                # Socket.IO ack mein JSON serialize nahi hota
                item.update(
                    kind="known",
                    label=info["name"],
                    status=status,
                    emp_id=int(emp_id),
                )

                # Zone processing payload
                detected_faces_for_zone.append(
                    {
                        "employee_id": int(emp_id),
                        "name": info["name"],
                        "bbox": box,
                    }
                )

            elif info and sim >= Config.MATCH_THRESHOLD - Config.UNCERTAIN_MARGIN:
                item.update(
                    kind="uncertain", label="Checking...", status="uncertain"
                )
            else:
                label, count = self._on_unknown(
                    frame, face, emb, box, source_id, source_name
                )
                item.update(
                    kind="unknown", label=label, status="unknown", count=count
                )
            results.append(item)

        # Zone detection triggering
        if isinstance(db_zones, dict) and db_zones and (camera_id or source_id):
            self.process_frame_attendance(
                camera_id or source_id, detected_faces_for_zone, db_zones
            )

        return results

    # ------------------------------------------------------------------ zone-based attendance
    @staticmethod
    def get_person_zone(face_point, door_zone_pts, exit_zone_pts):
        """face_point: (x, y) coordinates of recognized face

        door_zone_pts: [[x1, y1], [x2, y2], ...] exit_zone_pts: [[x1, y1], [x2,
        y2], ...]
        """
        x, y = face_point

        # 1. Check Door / Check-In Zone
        if door_zone_pts and len(door_zone_pts) >= 3:
            door_poly = np.array(door_zone_pts, dtype=np.int32)
            if (
                cv2.pointPolygonTest(
                    door_poly, (float(x), float(y)), False
                )
                >= 0
            ):
                return "check_in"

        # 2. Check Exit / Check-Out Zone
        if exit_zone_pts and len(exit_zone_pts) >= 3:
            exit_poly = np.array(exit_zone_pts, dtype=np.int32)
            if (
                cv2.pointPolygonTest(
                    exit_poly, (float(x), float(y)), False
                )
                >= 0
            ):
                return "check_out"

        return None

    def process_frame_attendance(self, camera_id, detected_faces, db_zones):
        """db_zones format: { 'door_zone': [[...]], 'exit_zone': [[...]] }"""
        door_pts = db_zones.get("door_zone") or []
        exit_pts = db_zones.get("exit_zone") or []

        for face in detected_faces:
            person_name = face.get("name", "Unknown")
            employee_id = face.get("employee_id")

            if not employee_id or person_name.lower() == "unknown":
                continue

            bbox = face.get("bbox", [])  # [x1, y1, x2, y2]
            if len(bbox) < 4:
                continue

            # Face Bounding Box Center Point
            center_x = int((bbox[0] + bbox[2]) / 2)
            center_y = int((bbox[1] + bbox[3]) / 2)

            # Detect Zone Event
            current_zone_event = self.get_person_zone((center_x, center_y), door_pts, exit_pts)

            if current_zone_event:
                self.record_attendance_event(employee_id, person_name, current_zone_event, camera_id)

    def record_attendance_event(self, employee_id, employee_name, event_type, camera_id):
        now = datetime.now()
        user_state = self._last_zone_event.get(employee_id)

        # Cooldown Logic: 10 seconds tak same action repeat nahi hoga
        if user_state:
            time_elapsed = (now - user_state["time"]).total_seconds()
            if user_state["last_event"] == event_type and time_elapsed < 10:
                return  # Skip duplicate log

        # State update
        self._last_zone_event[employee_id] = {
            "last_event": event_type,
            "time": now,
        }

        # DB Entry Logic
        try:
            with self._lock, self.app.app_context():
                today_date = now.date()
                rec = Attendance.query.filter_by(
                    employee_id=employee_id, date=today_date
                ).first()

                if event_type == "check_in":
                    if rec is None:
                        rec = Attendance(
                            employee_id=employee_id,
                            date=today_date,
                            check_in=now,
                            source_id=str(camera_id),
                        )
                        db.session.add(rec)
                    elif rec.check_in is None:
                        # Pehla check-in hi rakho; door zone mein khade rehne se
                        # time har 10s baad aage na khiske
                        rec.check_in = now
                elif event_type == "check_out":
                    if rec is None:
                        rec = Attendance(
                            employee_id=employee_id,
                            date=today_date,
                            check_out=now,
                            source_id=str(camera_id),
                        )
                        db.session.add(rec)
                    else:
                        rec.check_out = now

                db.session.commit()
        except Exception as exc:
            log_db(
                "ERROR",
                "system",
                str(camera_id),
                f"Zone Attendance DB error: {exc}",
                throttle=30,
            )

        # Emit Event to UI via Socket.IO
        # (namespace dena zaroori hai, warna event default "/" pe jata hai
        #  aur live.html ka io('/webcam') usse sunta hi nahi)
        if socketio:
            payload = {
                "employee_name": employee_name,
                "event_type": (
                    "CHECK-IN" if event_type == "check_in" else "CHECK-OUT"
                ),
                "time": now.strftime("%I:%M:%S %p"),
                "camera_id": camera_id,
            }
            for ns in _EVENT_NAMESPACES:
                try:
                    socketio.emit("new_attendance_event", payload, namespace=ns)
                except Exception as exc:
                    log_db(
                        "ERROR",
                        "system",
                        str(camera_id),
                        f"Attendance event emit failed ({ns}): {exc}",
                        throttle=30,
                    )

        log_db(
            "INFO",
            "attendance",
            str(camera_id),
            f"Zone Event {event_type.upper()}: {employee_name} on camera {camera_id}",
        )

    # ------------------------------------------------------------------ attendance
    def _on_known(self, emp_id, info, sim, source_id, source_name):
        now = time.time()
        key = (source_id, emp_id)
        cnt, last = self._streaks.get(key, (0, 0.0))
        cnt = cnt + 1 if now - last <= Config.STREAK_WINDOW else 1
        self._streaks[key] = (cnt, now)

        if cnt < Config.CONFIRM_FRAMES:
            return "verifying"
        if (
            now - self._last_marked.get(emp_id, 0)
            < Config.MARK_CACHE_SECONDS
        ):
            return "present"
        return self._mark(emp_id, info, sim, source_id, source_name)

    def _mark(self, emp_id, info, sim, source_id, source_name):
        action = None
        try:
            with self._lock, self.app.app_context():
                now = datetime.now()
                rec = Attendance.query.filter_by(
                    employee_id=emp_id, date=now.date()
                ).first()
                if rec is None:
                    db.session.add(
                        Attendance(
                            employee_id=emp_id,
                            date=now.date(),
                            check_in=now,
                            source_id=source_id,
                            similarity=float(sim),
                        )
                    )
                    action = "CHECK_IN"
                else:
                    ref = rec.check_out or rec.check_in
                    if (
                        now - ref
                    ).total_seconds() >= Config.CHECKOUT_GAP_MIN * 60:
                        rec.check_out = now
                        action = "CHECK_OUT"
                db.session.commit()
        except Exception as exc:
            log_db(
                "ERROR",
                "system",
                source_id,
                f"Attendance DB error: {exc}",
                throttle=30,
            )
            return "db_error"

        self._last_marked[emp_id] = time.time()
        if action:
            log_db(
                "INFO",
                "attendance",
                source_id,
                f"{action}: {info['name']} ({info['code']}) via {source_name or source_id}, sim={sim:.2f}",
            )
        return action or "present"

    # ------------------------------------------------------------------ unknown faces
    def _on_unknown(self, frame, face, emb, box, source_id, source_name):
        w, h = box[2] - box[0], box[3] - box[1]
        if (
            face.det_score < Config.UNKNOWN_MIN_DET_SCORE
            or min(w, h) < Config.UNKNOWN_MIN_FACE_PX
        ):
            return "Unknown", 0  # low quality: sirf dikhao, record mat karo

        event = None
        try:
            with self._lock, self.app.app_context():
                now = time.time()
                uid, sim = self.store.search_unknown(emb)
                u = None
                if (
                    uid is not None
                    and sim >= Config.UNKNOWN_MATCH_THRESHOLD
                ):
                    u = db.session.get(UnknownFace, uid)

                if u is not None:
                    prev = self._unknown_seen.get(u.id)
                    self._unknown_seen[u.id] = now
                    if (
                        prev is None
                        or now - prev >= Config.UNKNOWN_VISIT_GAP
                    ):
                        u.seen_count += 1
                        u.last_seen = datetime.now()
                        u.last_source = source_id
                        db.session.commit()
                        event = f"{u.label} dobara aaya (visit #{u.seen_count}) on {source_name or source_id}"
                    label, count = u.label, u.seen_count
                else:
                    u = UnknownFace(seen_count=1, last_source=source_id)
                    db.session.add(u)
                    db.session.flush()  # id mil jaye
                    u.label = f"UNK-{u.id:04d}"
                    u.snapshot = self._save_snapshot(
                        frame, box, f"{u.label}_{int(now)}"
                    )
                    db.session.commit()

                    self.store.add_unknown(u.id, emb)
                    self._unknown_seen[u.id] = now
                    event = f"Naya unknown face {u.label} on {source_name or source_id}"
                    label, count = u.label, 1
        except Exception as exc:
            log_db(
                "ERROR",
                "system",
                source_id,
                f"Unknown-face handling error: {exc}",
                throttle=30,
            )
            return "Unknown", 0

        if event:
            log_db("WARNING", "unknown", source_id, event)
        return label, count

    @staticmethod
    def _save_snapshot(frame, box, name):
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = box
        m = int(0.25 * max(x2 - x1, y2 - y1))
        crop = frame[
            max(0, y1 - m) : min(h, y2 + m), max(0, x1 - m) : min(w, x2 + m)
        ]
        rel = f"unknowns/{name}.jpg"
        cv2.imwrite(os.path.join(Config.STATIC_DIR, rel), crop)
        return rel

    # ------------------------------------------------------------------ registration
    def register_employee(self, code, name, department, frames):
        """(ok, message).

        Duplicate face ya duplicate code ho to reject.
        """
        code, name, department = (
            (code or "").strip(),
            (name or "").strip(),
            (department or "").strip(),
        )
        if not _CODE_RE.match(code):
            return (
                False,
                "Employee code sirf letters, numbers, - aur _ ho sakta hai (max 50).",
            )
        if not name or len(name) > 120:
            return False, "Name zaroori hai (max 120 characters)."
        if not frames:
            return False, "Koi frame nahi mila."

        samples, reasons = [], Counter()
        for fr in frames:
            faces = self.engine.detect(fr)
            if len(faces) != 1:
                reasons["frame mein exactly 1 face honi chahiye"] += 1
                continue
            ok, why = self.engine.quality_ok(fr, faces[0])
            if not ok:
                reasons[why] += 1
                continue
            samples.append(faces[0].normed_embedding)

        if len(samples) < Config.REG_MIN_SAMPLES:
            top = (
                reasons.most_common(1)[0][0] if reasons else "quality kam thi"
            )
            return (
                False,
                f"Sirf {len(samples)} achi frames mili (kam az kam {Config.REG_MIN_SAMPLES} chahiye): {top}.",
            )

        embs = np.stack(samples)
        center = embs.mean(axis=0)
        center /= np.linalg.norm(center)
        keep = [e for e in embs if float(e @ center) >= Config.REG_SELF_SIM]
        if len(keep) < Config.REG_MIN_SAMPLES:
            return (
                False,
                "Frames mein alag alag log lag rahe hain. Sirf ek banda camera ke saamne ho.",
            )

        with self._lock, self.app.app_context():
            # 1) duplicate face check (vector DB)
            for e in keep:
                eid, sim = self.store.search_employee(e)
                if eid is not None and sim >= Config.DUPLICATE_THRESHOLD:
                    info = self._emp_cache.get(eid, {"name": "?", "code": "?"})
                    log_db(
                        "WARNING",
                        "register",
                        "register",
                        f"Duplicate face rejected: '{name}' ({code}) already registered as "
                        f"{info['name']} ({info['code']}), sim={sim:.2f}",
                    )
                    return False, (
                        f"Ye face pehle se registered hai: {info['name']} ({info['code']}), "
                        f"similarity {sim:.2f}."
                    )

            # 2) duplicate code check (MySQL)
            if Employee.query.filter_by(emp_code=code).first():
                return (
                    False,
                    f"Employee code '{code}' pehle se maujood hai.",
                )

            # 3) save: MySQL + vector DB (dono ya koi nahi)
            emp = Employee(emp_code=code, name=name, department=department)
            db.session.add(emp)
            try:
                db.session.flush()
                self.store.add_employee(emp.id, keep)
                db.session.commit()
            except Exception as exc:
                db.session.rollback()
                if emp.id:
                    try:
                        self.store.delete_employee(emp.id)
                    except Exception:
                        pass
                log_db(
                    "ERROR",
                    "system",
                    "register",
                    f"Registration failed for {code}: {exc}",
                )
                return (
                    False,
                    "Server error: registration save nahi ho saki.",
                )
            emp_id = emp.id

        self.reload_cache()
        log_db(
            "INFO",
            "register",
            "register",
            f"Registered: {name} ({code}) with {len(keep)} face samples (id={emp_id})",
        )
        return True, f"{name} register ho gaya ({len(keep)} face samples)."

    def delete_employee(self, emp_id):
        try:
            with self._lock, self.app.app_context():
                emp = db.session.get(Employee, int(emp_id))
                if emp is None:
                    return False, "Employee nahi mila."
                name, code = emp.name, emp.emp_code
                db.session.delete(
                    emp
                )  # attendance rows bhi delete hongi (cascade)
                db.session.commit()
            self.store.delete_employee(int(emp_id))
        except Exception as exc:
            log_db(
                "ERROR",
                "system",
                "register",
                f"Delete failed for id={emp_id}: {exc}",
            )
            return False, "Server error: delete nahi ho saka."
        self.reload_cache()
        log_db(
            "INFO", "register", "register", f"Deleted employee: {name} ({code})"
        )
        return True, f"{name} delete ho gaya."

    def list_employees(self):
        with self.app.app_context():
            return [
                {
                    "id": e.id,
                    "code": e.emp_code,
                    "name": e.name,
                    "department": e.department or "",
                    "created": e.created_at.strftime("%Y-%m-%d"),
                }
                for e in Employee.query.order_by(Employee.name).all()
            ]