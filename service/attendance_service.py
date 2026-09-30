"""Core logic: recognise -> attendance / unknown tracking / registration.
CCTV threads aur webcam socket dono yahi service use karte hain."""
import os
import re
import threading
import time
from collections import Counter
from datetime import datetime

import cv2
import numpy as np

from config.config import Config
from extensions import db
from logging_utils import log_db
from models import Attendance, Employee, UnknownFace

_CODE_RE = re.compile(r"^[A-Za-z0-9_\-]{1,50}$")


class AttendanceService:
    def __init__(self, app, engine, store):
        self.app = app
        self.engine = engine
        self.store = store
        self._lock = threading.RLock()
        self._streaks = {}        # (source_id, emp_id) -> (count, last_ts)
        self._last_marked = {}    # emp_id -> ts
        self._unknown_seen = {}   # unknown_id -> ts (last dekha gaya)
        self._emp_cache = {}      # emp_id -> {"name", "code"}
        self.reload_cache()

    def reload_cache(self):
        with self.app.app_context():
            self._emp_cache = {e.id: {"name": e.name, "code": e.emp_code} for e in Employee.query.all()}

    # ------------------------------------------------------------------ recognition
    def process(self, frame, source_id, source_name=""):
        """Ek frame process karo. Har face ke liye dict wapas karta hai (box, kind, label, status...)."""
        results = []
        for face in self.engine.detect(frame):
            emb = face.normed_embedding
            box = [int(v) for v in face.bbox]
            emp_id, sim = self.store.search_employee(emb)
            info = self._emp_cache.get(emp_id) if emp_id is not None else None
            item = {"box": box, "sim": round(float(sim), 3)}

            if info and sim >= Config.MATCH_THRESHOLD:
                status = self._on_known(emp_id, info, sim, source_id, source_name)
                item.update(kind="known", label=info["name"], status=status)
            elif info and sim >= Config.MATCH_THRESHOLD - Config.UNCERTAIN_MARGIN:
                item.update(kind="uncertain", label="Checking...", status="uncertain")
            else:
                label, count = self._on_unknown(frame, face, emb, box, source_id, source_name)
                item.update(kind="unknown", label=label, status="unknown", count=count)
            results.append(item)
        return results

    # ------------------------------------------------------------------ attendance
    def _on_known(self, emp_id, info, sim, source_id, source_name):
        now = time.time()
        key = (source_id, emp_id)
        cnt, last = self._streaks.get(key, (0, 0.0))
        cnt = cnt + 1 if now - last <= Config.STREAK_WINDOW else 1
        self._streaks[key] = (cnt, now)

        if cnt < Config.CONFIRM_FRAMES:
            return "verifying"
        if now - self._last_marked.get(emp_id, 0) < Config.MARK_CACHE_SECONDS:
            return "present"
        return self._mark(emp_id, info, sim, source_id, source_name)

    def _mark(self, emp_id, info, sim, source_id, source_name):
        action = None
        try:
            with self._lock, self.app.app_context():
                now = datetime.now()
                rec = Attendance.query.filter_by(employee_id=emp_id, date=now.date()).first()
                if rec is None:
                    db.session.add(
                        Attendance(
                            employee_id=emp_id, date=now.date(), check_in=now,
                            source_id=source_id, similarity=float(sim),
                        )
                    )
                    action = "CHECK_IN"
                else:
                    ref = rec.check_out or rec.check_in
                    if (now - ref).total_seconds() >= Config.CHECKOUT_GAP_MIN * 60:
                        rec.check_out = now
                        action = "CHECK_OUT"
                db.session.commit()
        except Exception as exc:
            log_db("ERROR", "system", source_id, f"Attendance DB error: {exc}", throttle=30)
            return "db_error"

        self._last_marked[emp_id] = time.time()
        if action:
            log_db(
                "INFO", "attendance", source_id,
                f"{action}: {info['name']} ({info['code']}) via {source_name or source_id}, sim={sim:.2f}",
            )
        return action or "present"

    # ------------------------------------------------------------------ unknown faces
    def _on_unknown(self, frame, face, emb, box, source_id, source_name):
        w, h = box[2] - box[0], box[3] - box[1]
        if face.det_score < Config.UNKNOWN_MIN_DET_SCORE or min(w, h) < Config.UNKNOWN_MIN_FACE_PX:
            return "Unknown", 0  # low quality: sirf dikhao, record mat karo

        event = None
        try:
            with self._lock, self.app.app_context():
                now = time.time()
                uid, sim = self.store.search_unknown(emb)
                u = None
                if uid is not None and sim >= Config.UNKNOWN_MATCH_THRESHOLD:
                    u = db.session.get(UnknownFace, uid)

                if u is not None:
                    prev = self._unknown_seen.get(u.id)
                    self._unknown_seen[u.id] = now
                    if prev is None or now - prev >= Config.UNKNOWN_VISIT_GAP:
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
                    u.snapshot = self._save_snapshot(frame, box, f"{u.label}_{int(now)}")
                    db.session.commit()

                    self.store.add_unknown(u.id, emb)
                    self._unknown_seen[u.id] = now
                    event = f"Naya unknown face {u.label} on {source_name or source_id}"
                    label, count = u.label, 1
        except Exception as exc:
            log_db("ERROR", "system", source_id, f"Unknown-face handling error: {exc}", throttle=30)
            return "Unknown", 0

        if event:
            log_db("WARNING", "unknown", source_id, event)
        return label, count

    @staticmethod
    def _save_snapshot(frame, box, name):
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = box
        m = int(0.25 * max(x2 - x1, y2 - y1))
        crop = frame[max(0, y1 - m):min(h, y2 + m), max(0, x1 - m):min(w, x2 + m)]
        rel = f"unknowns/{name}.jpg"
        cv2.imwrite(os.path.join(Config.STATIC_DIR, rel), crop)
        return rel

    # ------------------------------------------------------------------ registration
    def register_employee(self, code, name, department, frames):
        """(ok, message). Duplicate face ya duplicate code ho to reject."""
        code, name, department = (code or "").strip(), (name or "").strip(), (department or "").strip()
        if not _CODE_RE.match(code):
            return False, "Employee code sirf letters, numbers, - aur _ ho sakta hai (max 50)."
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
            top = reasons.most_common(1)[0][0] if reasons else "quality kam thi"
            return False, f"Sirf {len(samples)} achi frames mili (kam az kam {Config.REG_MIN_SAMPLES} chahiye): {top}."

        embs = np.stack(samples)
        center = embs.mean(axis=0)
        center /= np.linalg.norm(center)
        keep = [e for e in embs if float(e @ center) >= Config.REG_SELF_SIM]
        if len(keep) < Config.REG_MIN_SAMPLES:
            return False, "Frames mein alag alag log lag rahe hain. Sirf ek banda camera ke saamne ho."

        with self._lock, self.app.app_context():
            # 1) duplicate face check (vector DB)
            for e in keep:
                eid, sim = self.store.search_employee(e)
                if eid is not None and sim >= Config.DUPLICATE_THRESHOLD:
                    info = self._emp_cache.get(eid, {"name": "?", "code": "?"})
                    log_db(
                        "WARNING", "register", "register",
                        f"Duplicate face rejected: '{name}' ({code}) already registered as "
                        f"{info['name']} ({info['code']}), sim={sim:.2f}",
                    )
                    return False, (
                        f"Ye face pehle se registered hai: {info['name']} ({info['code']}), "
                        f"similarity {sim:.2f}."
                    )

            # 2) duplicate code check (MySQL)
            if Employee.query.filter_by(emp_code=code).first():
                return False, f"Employee code '{code}' pehle se maujood hai."

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
                log_db("ERROR", "system", "register", f"Registration failed for {code}: {exc}")
                return False, "Server error: registration save nahi ho saki."
            emp_id = emp.id

        self.reload_cache()
        log_db("INFO", "register", "register", f"Registered: {name} ({code}) with {len(keep)} face samples (id={emp_id})")
        return True, f"{name} register ho gaya ({len(keep)} face samples)."

    def delete_employee(self, emp_id):
        try:
            with self._lock, self.app.app_context():
                emp = db.session.get(Employee, int(emp_id))
                if emp is None:
                    return False, "Employee nahi mila."
                name, code = emp.name, emp.emp_code
                db.session.delete(emp)  # attendance rows bhi delete hongi (cascade)
                db.session.commit()
            self.store.delete_employee(int(emp_id))
        except Exception as exc:
            log_db("ERROR", "system", "register", f"Delete failed for id={emp_id}: {exc}")
            return False, "Server error: delete nahi ho saka."
        self.reload_cache()
        log_db("INFO", "register", "register", f"Deleted employee: {name} ({code})")
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
