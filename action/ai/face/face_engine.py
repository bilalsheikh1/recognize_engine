import threading
import cv2
from insightface.app import FaceAnalysis

from config.config import Config


class FaceEngine:
    def __init__(self):
        # pehli baar buffalo_l (~280MB) ~/.insightface mein download hota hai
        self.app = FaceAnalysis(
            name=Config.MODEL_NAME,
            allowed_modules=["detection", "landmark_3d_68", "recognition"],
            providers=Config.ONNX_PROVIDERS,
        )
        self.app.prepare(ctx_id=Config.CTX_ID, det_size=Config.DET_SIZE)
        self._lock = threading.Lock()  # multiple threads ek hi model use karte hain

    def detect(self, bgr):
        """Frame se achi quality ke faces (embedding ke saath) wapas karta hai."""
        with self._lock:
            faces = self.app.get(bgr)
        out = []
        for f in faces:
            x1, y1, x2, y2 = f.bbox
            if f.det_score < Config.MIN_DET_SCORE or min(x2 - x1, y2 - y1) < Config.MIN_FACE_PX:
                continue
            if f.normed_embedding.shape[0] != Config.EMBEDDING_DIM:
                continue
            out.append(f)
        return out

    @staticmethod
    def quality_ok(bgr, face):
        """Registration ke liye sakht quality check. (ok, reason) wapas karta hai."""
        x1, y1, x2, y2 = [int(v) for v in face.bbox]
        if face.det_score < Config.REG_MIN_DET_SCORE:
            return False, "face clear detect nahi hui"
        if min(x2 - x1, y2 - y1) < Config.REG_MIN_FACE_PX:
            return False, "camera ke thora qareeb aayein"
        pose = getattr(face, "pose", None)  # [pitch, yaw, roll]
        if pose is not None and (
            abs(pose[0]) > Config.REG_MAX_POSE or abs(pose[1]) > Config.REG_MAX_POSE
        ):
            return False, "chehra camera ki taraf seedha rakhein"
        h, w = bgr.shape[:2]
        crop = bgr[max(0, y1) : min(h, y2), max(0, x1) : min(w, x2)]
        if crop.size == 0:
            return False, "face crop invalid"
        gray = cv2.cvtColor(cv2.resize(crop, (160, 160)), cv2.COLOR_BGR2GRAY)
        if cv2.Laplacian(gray, cv2.CV_64F).var() < Config.REG_MIN_SHARPNESS:
            return False, "image blur hai"
        return True, ""




