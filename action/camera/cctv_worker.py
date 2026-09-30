import threading
from logging_utils import log_db
from extensions import socketio
from config.config import Config
import cv2
import base64
import time


class CCTVWorker:
    def __init__(self, cam, service):
        self.cam = cam
        self.service = service
        src = cam["source"]
        self.source = int(src) if isinstance(src, str) and src.isdigit() else src
        self.is_live = isinstance(self.source, int) or str(self.source).lower().startswith(("rtsp", "http", "rtmp"))
        self.online = None  # None = abhi tak pata nahi
        self._latest = None
        self._frame_lock = threading.Lock()
        self._stop = threading.Event()
        self._threads = [
            threading.Thread(target=self._read_loop, name=f"read-{cam['id']}", daemon=True),
            threading.Thread(target=self._process_loop, name=f"proc-{cam['id']}", daemon=True),
        ]
        self.colors = {"known": (60, 200, 60), "unknown": (50, 50, 230), "uncertain": (0, 165, 255)}
        self.font = cv2.FONT_HERSHEY_SIMPLEX

    def start(self):
        for t in self._threads:
            t.start()

    def stop(self):
        self._stop.set()

    # ---------------------------------------------------------------- status
    def _set_online(self, online, reason=""):
        if self.online == online:
            return
        self.online = online
        name = self.cam["name"]
        if online:
            log_db("INFO", "camera", self.cam["id"], f"{name} online")
        else:
            log_db("ERROR", "camera", self.cam["id"], f"{name} offline: {reason}")
        socketio.emit("camera_status", {"camera_id": self.cam["id"], "online": online}, namespace="/cctv")

    def _open(self):
        if isinstance(self.source, int):
            cap = cv2.VideoCapture(self.source)
        else:
            cap = cv2.VideoCapture(
                self.source, cv2.CAP_FFMPEG,
                [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 8000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 8000],
            )
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap

    # ---------------------------------------------------------------- thread 1: reader
    def _read_loop(self):
        cap, backoff = None, 1
        while not self._stop.is_set():
            try:
                if cap is None or not cap.isOpened():
                    cap = self._open()
                    if not cap.isOpened():
                        cap.release()
                        cap = None
                        self._set_online(False, "stream open nahi hui")
                        self._stop.wait(backoff)
                        backoff = min(backoff * 2, 30)
                        continue
                    backoff = 1
                    self._set_online(True)

                ok, frame = cap.read()
                if not ok or frame is None:
                    cap.release()
                    cap = None
                    self._set_online(False, "stream lost / frame nahi mila")
                    self._stop.wait(backoff)
                    continue

                with self._frame_lock:
                    self._latest = frame
                if not self.is_live:
                    time.sleep(0.03)  # video file test mode: real-time speed
            except Exception as exc:
                cap = None
                self._set_online(False, f"reader exception: {exc}")
                self._stop.wait(backoff)
        if cap is not None:
            cap.release()

    # ---------------------------------------------------------------- thread 2: processor
    def _process_loop(self):
        cid = self.cam["id"]
        while not self._stop.is_set():
            self._stop.wait(Config.PROCESS_INTERVAL)
            with self._frame_lock:
                frame, self._latest = self._latest, None
            if frame is None:
                continue
            try:
                results = self.service.process(frame, cid, self.cam["name"])
                image = self.to_b64_jpeg(self.annotate(frame, results))
                if image:
                    socketio.emit(
                        "cctv_frame",
                        {"camera_id": cid, "image": image, "faces": len(results)},
                        namespace="/cctv",
                    )
            except Exception as exc:
                log_db("ERROR", "system", cid, f"Processing error: {exc}\n{traceback.format_exc()}", throttle=30)

    def to_b64_jpeg(self, frame, max_w=960, quality=65):
        h, w = frame.shape[:2]
        if w > max_w:
            frame = cv2.resize(frame, (max_w, int(h * max_w / w)))
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return base64.b64encode(buf).decode() if ok else None

    def annotate(self, frame, results):
        h, w = frame.shape[:2]
        scale, th = max(0.5, w / 1280), max(1, int(w / 640))
        for r in results:
            x1, y1, x2, y2 = r["box"]
            color = self.colors.get(r["kind"], (200, 200, 200))
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, th + 1)
            text = r["label"]
            if r["kind"] == "known":
                text += f" {r['sim']:.2f}"
            elif r["kind"] == "unknown" and r.get("count"):
                text += f" x{r['count']}"
            (tw, tht), _ = cv2.getTextSize(text, self.font, 0.6 * scale, th)
            cv2.rectangle(frame, (x1, y1 - tht - 10), (x1 + tw + 6, y1), color, -1)
            cv2.putText(frame, text, (x1 + 3, y1 - 5), self.font, 0.6 * scale, (255, 255, 255), th, cv2.LINE_AA)
        return frame