import cv2
import numpy as np
from insightface.app import FaceAnalysis
import time
import os
from datetime import datetime

class InsightFaceDetector:
    def __init__(self, match_threshold=0.45, save_dir="unknown_faces"):
        self.match_threshold = match_threshold
        self.known_faces = {}
        self.attendance_log = {}
        self.cooldown_seconds = 30

        # Blink Detection Tracking State
        self.blink_tracker = {}  # {person_id: {"blink_counter": int, "is_live": bool}}

        # Standard InsightFace Analysis
        # self.app = FaceAnalysis(
        #     name="buffalo_l",
        #     providers=['CUDAExecutionProvider', 'CPUExecutionProvider'],
        #     allowed_modules=['detection', 'recognition']
        # )
        self.app = FaceAnalysis(
            name="buffalo_l",
            providers=['CPUExecutionProvider'],
            allowed_modules=['detection', 'recognition'],
            addons = ["liveness"]
        )
        self.save_dir = save_dir
        self.unknown_log = {}  # Tracking timestamps to prevent spamming duplicate crops
        self.unknown_cooldown = 5  # Save 1 image per unknown person every 5 seconds
        if not os.path.exists(self.save_dir):
            os.makedirs(self.save_dir)
        self.app.prepare(ctx_id=0, det_size=(640, 640))

    def _save_unknown_crop(self, frame, bbox):
        """Crop and save unknown person face image with timestamp"""
        current_time = time.time()

        # Simple spatial identifier based on bbox center to avoid saving same face every frame
        h, w, _ = frame.shape
        x1, y1, x2, y2 = max(0, bbox[0]), max(0, bbox[1]), min(w, bbox[2]), min(h, bbox[3])
        face_center_id = f"unk_{int((x1 + x2) / 2 // 50)}_{int((y1 + y2) / 2 // 50)}"

        # Cooldown check
        if face_center_id in self.unknown_log:
            if current_time - self.unknown_log[face_center_id] < self.unknown_cooldown:
                return

        self.unknown_log[face_center_id] = current_time

        # Crop face area with a small padding
        pad_x = int((x2 - x1) * 0.2)
        pad_y = int((y2 - y1) * 0.2)
        crop_x1 = max(0, x1 - pad_x)
        crop_y1 = max(0, y1 - pad_y)
        crop_x2 = min(w, x2 + pad_x)
        crop_y2 = min(h, y2 + pad_y)

        face_crop = frame[crop_y1:crop_y2, crop_x1:crop_x2]

        if face_crop.size > 0:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]
            filename = os.path.join(self.save_dir, f"unknown_{timestamp}.jpg")
            cv2.imwrite(filename, face_crop)
            print(f"[UNKNOWN SAVED] Captured unknown face: {filename}")

    def register_face(self, name, image_path):
        img = cv2.imread(image_path)
        if img is None:
            return False

        faces = self.app.get(img)
        if len(faces) == 0:
            return False

        raw_emb = faces[0].embedding
        norm = np.linalg.norm(raw_emb)
        if norm == 0 or np.isnan(norm):
            return False

        self.known_faces[name] = raw_emb / norm
        print(f"[Success] Registered: {name}")
        return True

    def _calculate_ear(self, landmarks):
        """Eye Aspect Ratio (EAR) calculate karne ke liye helper method"""
        # Right & Left Eye Landmarks from InsightFace 5-point / 68-point alignment
        # Distance between eye keypoints
        left_eye = landmarks[1]  # Left eye center
        right_eye = landmarks[0]  # Right eye center
        nose = landmarks[2]

        # Micro movement / aspect ratio approximation
        dist = np.linalg.norm(left_eye - right_eye)
        return dist

    def _check_eye_blink(self, face, face_id):
        """Active Liveness: Landmarks analysis for natural eye movements"""
        if not hasattr(face, 'kps') or face.kps is None:
            return False

        kps = face.kps  # 5 Keypoints: [right_eye, left_eye, nose, mouth_right, mouth_left]

        # Calculate eye distance vs face width ratio
        bbox = face.bbox
        face_width = bbox[2] - bbox[0]
        eye_dist = np.linalg.norm(kps[0] - kps[1])
        ratio = eye_dist / face_width if face_width > 0 else 0

        # Dynamic state update
        if face_id not in self.blink_tracker:
            self.blink_tracker[face_id] = {"ratio_history": [], "is_live": False}

        history = self.blink_tracker[face_id]["ratio_history"]
        history.append(ratio)
        if len(history) > 10:
            history.pop(0)

        # Variance check: Real human eyes have continuous micro-movements/blinks
        # Static mobile photo will have 0 variance in landmark ratios across frames
        if len(history) >= 5:
            variance = np.var(history)
            if variance > 0.000015:  # Micro-movement detected
                self.blink_tracker[face_id]["is_live"] = True

        return self.blink_tracker[face_id]["is_live"]

    def _recognize_face(self, target_embedding):
        if not self.known_faces or target_embedding is None:
            return "Unknown", 0.0

        target_norm = np.linalg.norm(target_embedding)
        if target_norm == 0 or np.isnan(target_norm):
            return "Unknown", 0.0

        norm_target = target_embedding / target_norm
        best_name = "Unknown"
        max_sim = 0.0

        for name, known_emb in self.known_faces.items():
            if known_emb is None:
                continue
            sim = np.dot(norm_target, known_emb)
            if sim > max_sim:
                max_sim = sim
                best_name = name

        if max_sim >= self.match_threshold:
            return best_name, max_sim

        return "Unknown", max_sim

    def _mark_attendance(self, name):
        current_time = time.time()
        if name in self.attendance_log:
            if current_time - self.attendance_log[name] < self.cooldown_seconds:
                return False

        self.attendance_log[name] = current_time
        timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[ATTENDANCE MARKED] {name} at {timestamp_str}")
        return True

    def enhance_frame(self, frame):
        # YUV Color Space mein Convert karke Luminance boost karein
        img_yuv = cv2.cvtColor(frame, cv2.COLOR_BGR2YUV)
        img_yuv[:, :, 0] = cv2.equalizeHist(img_yuv[:, :, 0])
        enhanced = cv2.cvtColor(img_yuv, cv2.COLOR_YUV2BGR)
        return enhanced

    def process(self, frame):
        if frame is None:
            return None
        # frame = self.enhance_frame(frame)
        faces = self.app.get(frame)
        annotated_frame = frame.copy()

        for idx, face in enumerate(faces):
            bbox = face.bbox.astype(int)
            pt1, pt2 = (bbox[0], bbox[1]), (bbox[2], bbox[3])

            person_name, sim_score = self._recognize_face(face.embedding)

            # Active Liveness Check
            face_id = f"{person_name}_{idx}"
            is_live = self._check_eye_blink(face, face_id)

            # Strict Display Logic
            if is_live:
                if person_name != "Unknown":
                    marked = self._mark_attendance(person_name)
                    status = "Marked" if marked else "Recorded"
                    label = f"{person_name} ({sim_score:.2f}) - {status}"
                    color = (0, 255, 0)  # Green
                else:
                    label = f"Unknown ({sim_score:.2f}) - Live"
                    color = (0, 255, 255)  # Yellow
                    # ==========================================
                    # CAPTURE & SAVE UNKNOWN CLEAR CROP
                    # ==========================================
                    self._save_unknown_crop(frame, bbox)
            else:
                label = f"SPOOF/MOBILE IMAGE"
                color = (0, 0, 255)  # Red

            cv2.rectangle(annotated_frame, pt1, pt2, color, 2)
            cv2.putText(
                annotated_frame,
                label,
                (pt1[0], max(pt1[1] - 10, 15)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                color,
                2
            )

        return annotated_frame