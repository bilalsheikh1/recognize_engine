"""CCTV cameras: har camera ke liye 2 threads.
  reader    -> stream se frames padhta rehta hai (sirf latest frame rakhta hai, lag nahi banta)
  processor -> latest frame par face recognition + /cctv socket par preview bhejta hai
Stream toot jaye to auto-reconnect (exponential backoff) aur logs mein entry."""

from logging_utils import log_db
from .cctv_worker import CCTVWorker

class CameraManager:

    def __init__(self, cameras, service):
        # Helper function jo dict aur ORM object dono ko handle kare
        def get_val(obj, key):
            if isinstance(obj, dict):
                return obj.get(key)
            return getattr(obj, key, None)

        # Unique ID check
        ids = [get_val(c, "id") for c in cameras]
        if len(ids) != len(set(ids)):
            raise ValueError(
                "CAMERAS array mein camera ids unique honi chahiye"
            )

        # Clean dictionary structure normalize karein
        self.cameras = [
            {
                "id": get_val(c, "id"),
                "name": get_val(c, "name"),
                "type": get_val(c, "type"),
                "rtsp_url": get_val(c, "rtsp_url"),
                "source": get_val(c, "source"),
            }
            for c in cameras
        ]
        self.service = service
        self.workers = {}

    def start(self):
        for cam in self.cameras:
            if cam["type"] == "cctv":
                w = CCTVWorker(cam, self.service)
                self.workers[cam["id"]] = w
                w.start()

        n_cctv = len(self.workers)
        n_web = sum(1 for c in self.cameras if c["type"] == "webcam")
        log_db(
            "INFO",
            "system",
            "camera-manager",
            f"Started {n_cctv} CCTV worker(s) ({n_cctv * 2} threads), {n_web} webcam socket source(s)",
        )

    def info(self):
        out = []
        for c in self.cameras:
            w = self.workers.get(c["id"])
            out.append(
                {
                    "id": c["id"],
                    "name": c["name"],
                    "type": c["type"],
                    "online": w.online if w else None,
                }
            )
        return out