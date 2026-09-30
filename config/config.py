"""Saari settings yahan hain — camera array bhi yahin hai."""
import os
from urllib.parse import quote_plus

from dotenv import load_dotenv

load_dotenv()

# cv2 import hone se PEHLE set hona chahiye: RTSP ko TCP par force karta hai (green/broken frames kam)
os.environ.setdefault(
    "OPENCV_FFMPEG_CAPTURE_OPTIONS",
    "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay",
)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
_USE_GPU = os.getenv("USE_GPU", "0") == "1"


class Config:
    # ---------------- Flask / server ----------------
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
    ADMIN_KEY = os.getenv("ADMIN_KEY", "admin123")  # register/delete ke liye (production mein zaroor badlein)
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", "5000"))
    SSL_CERT = os.getenv("SSL_CERT", "")  # LAN se webcam use karna ho to HTTPS chahiye
    SSL_KEY = os.getenv("SSL_KEY", "")
    CORS_ORIGINS = "*"

    # ---------------- MySQL ----------------
    DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
    DB_PORT = int(os.getenv("DB_PORT", "3306"))
    DB_USER = os.getenv("DB_USER", "root")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "")
    DB_NAME = os.getenv("DB_NAME", "face_attendance")
    SQLALCHEMY_DATABASE_URI = (
        f"mysql+pymysql://{DB_USER}:{quote_plus(DB_PASSWORD)}@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"
    )
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 280,
        "pool_size": 10,
        "max_overflow": 20,
    }
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # ---------------- Paths ----------------
    STATIC_DIR = os.path.join(BASE_DIR, "../static")
    CHROMA_PATH = os.path.join(BASE_DIR, "../chroma_data")
    LOG_DIR = os.path.join(BASE_DIR, "../logs")

    # ---------------- CAMERA ARRAY ----------------
    # Is ek array mein CCTV aur webcam dono aate hain. Array ka size = total cameras.
    #   type="cctv"   -> server khud stream kholta hai (RTSP url / video file path / local camera index)
    #                    har CCTV ke liye 2 threads: reader + processor
    #   type="webcam" -> browser ka webcam, frames /webcam socket se aate hain
    CAMERAS = [
        # {
        #     "id": "cctv-1",
        #     "name": "Main Gate",
        #     "type": "cctv",
        #     "source": os.getenv("CCTV_1", "rtsp://admin:password@192.168.1.64:554/Streaming/Channels/101"),
        # },
        # {
        #     "id": "cctv-2",
        #     "name": "Office Hall",
        #     "type": "cctv",
        #     "source": os.getenv("CCTV_2", "rtsp://admin:password@192.168.1.65:554/Streaming/Channels/101"),
        # },
        {"id": "webcam-1", "name": "Reception Webcam", "type": "webcam", "source": None},
    ]
    PROCESS_INTERVAL = 0.25  # CCTV frame processing gap (seconds) ~ 4 fps

    # ---------------- InsightFace ----------------
    MODEL_NAME = "buffalo_l"  # ArcFace w600k_r50 -> 512-dim embedding
    ONNX_PROVIDERS = ["CUDAExecutionProvider", "CPUExecutionProvider"] if _USE_GPU else ["CPUExecutionProvider"]
    CTX_ID = 0 if _USE_GPU else -1
    DET_SIZE = (640, 640)
    EMBEDDING_DIM = 512
    MIN_DET_SCORE = 0.60
    MIN_FACE_PX = 60

    # ---------------- Matching (cosine similarity) ----------------
    MATCH_THRESHOLD = 0.50        # isse upar = employee pehchana gaya
    UNCERTAIN_MARGIN = 0.10       # (0.40 - 0.50) = "checking", na unknown record hota hai na attendance
    DUPLICATE_THRESHOLD = 0.50    # registration par: isse upar = face pehle se registered
    UNKNOWN_MATCH_THRESHOLD = 0.50
    UNKNOWN_MIN_DET_SCORE = 0.75  # sirf achi quality wale unknown faces record hotay hain
    UNKNOWN_MIN_FACE_PX = 80
    UNKNOWN_VISIT_GAP = 60        # itni der ghayab rehne ke baad wapas aaye to nayi visit count hogi (seconds)

    # ---------------- Attendance ----------------
    CONFIRM_FRAMES = 2            # attendance se pehle itne qareebi frames mein same banda match hona chahiye
    STREAK_WINDOW = 3.0           # seconds
    MARK_CACHE_SECONDS = 60       # DB par bar bar hit na ho
    CHECKOUT_GAP_MIN = 30         # check-in ke itne minute baad dobara dikha to check_out update hoga

    # ---------------- Registration ----------------
    REG_MIN_SAMPLES = 5
    REG_MIN_DET_SCORE = 0.75
    REG_MIN_FACE_PX = 90
    REG_MIN_SHARPNESS = 40.0
    REG_MAX_POSE = 30             # degrees (yaw/pitch)
    REG_SELF_SIM = 0.60           # ek hi banday ke samples ek doosre se itne similar hon
