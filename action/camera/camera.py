import cv2
import threading
import time
from insightface.app import FaceAnalysis

class Camera:

    def __init__(self, camera_id, config):
        self.camera_id = camera_id
        self.camera_type = config["type"]
        self.source = config["source"]

        self.cap = None
        self.running = False
        self.lock = threading.Lock()

        self.latest_frame = None
        self.latest_annotated = None

        self.thread = threading.Thread(
            target=self.run,
            daemon=True
        )

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread.start()

    def connect(self):
        print(f"[{self.camera_id}] Connecting to {self.source}...")

        if self.camera_type == "webcam":
            self.cap = cv2.VideoCapture(self.source)
        elif self.camera_type in ["rtsp", "http"]:
            self.cap = cv2.VideoCapture(self.source, cv2.CAP_FFMPEG)
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        else:
            print(f"[{self.camera_id}] Unknown camera type: {self.camera_type}")
            return False

        if self.cap and self.cap.isOpened():
            print(f"[{self.camera_id}] Connected successfully")
            return True

        print(f"[{self.camera_id}] Connection failed")
        if self.cap:
            self.cap.release()
            self.cap = None
        return False

    def run(self):
        while self.running:
            if self.cap is None or not self.cap.isOpened():
                if not self.connect():
                    time.sleep(2)
                    continue

            success, frame = self.cap.read()

            if not success or frame is None:
                print(f"[{self.camera_id}] Frame read failed")
                if self.cap:
                    self.cap.release()
                    self.cap = None
                time.sleep(1)
                continue

            # Frame Resize (Optionally standard 640x480 resolution to prevent huge bounding boxes)
            frame = cv2.resize(frame, (640, 360))

            with self.lock:
                self.latest_frame = frame.copy()

            annotated = frame
            if hasattr(self, "process_frame") and callable(self.process_frame):
                try:
                    annotated = self.process_frame(frame)
                    if annotated is None:
                        annotated = frame
                except Exception as e:
                    print(f"[{self.camera_id}] AI Error: {e}")
                    annotated = frame

            with self.lock:
                self.latest_annotated = annotated.copy()

            time.sleep(0.02)  # High FPS stability

    def get_frame(self):
        with self.lock:
            if self.latest_annotated is None:
                return None
            return self.latest_annotated.copy()

    def stop(self):
        self.running = False
        if self.cap:
            self.cap.release()
            self.cap = None
        print(f"[{self.camera_id}] Stopped")