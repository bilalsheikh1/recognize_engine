"""CCTV cameras: har camera ke liye 2 threads.
  reader    -> stream se frames padhta rehta hai (sirf latest frame rakhta hai, lag nahi banta)
  processor -> latest frame par face recognition + /cctv socket par preview bhejta hai
Stream toot jaye to auto-reconnect (exponential backoff) aur logs mein entry."""

from logging_utils import log_db
from .cctv_worker import CCTVWorker

def _get_val(obj, key):
    """Dict aur ORM object dono ko handle karne wala helper."""
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _normalize_camera(c):
    return {
        "id": _get_val(c, "id"),
        "name": _get_val(c, "name"),
        "type": _get_val(c, "type"),
        "rtsp_url": _get_val(c, "rtsp_url"),
        "source": _get_val(c, "source"),
    }


class CameraManager:

    def __init__(self, cameras, service):
        # Unique ID check
        ids = [_get_val(c, "id") for c in cameras]
        if len(ids) != len(set(ids)):
            raise ValueError(
                "CAMERAS array mein camera ids unique honi chahiye"
            )

        # Clean dictionary structure normalize karein
        self.cameras = [_normalize_camera(c) for c in cameras]
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

    def add_camera(self, cam):
        """Camera Management page se naya camera add hone par turant (server restart ke bina)
        uska worker start karta hai — warna agla CCTV camera tab tak stream nahi karta
        jab tak app dobara start na ho."""
        cam_dict = _normalize_camera(cam)
        if any(c["id"] == cam_dict["id"] for c in self.cameras):
            return

        self.cameras.append(cam_dict)
        if cam_dict["type"] == "cctv":
            w = CCTVWorker(cam_dict, self.service)
            self.workers[cam_dict["id"]] = w
            w.start()
            log_db(
                "INFO", "system", "camera-manager",
                f"CCTV worker {cam_dict['id']} on-the-fly start hua (naya camera add)",
            )

    def remove_camera(self, camera_id):
        """Camera delete hone par uska running worker (agar CCTV hai) band karta hai,
        taake deleted camera ka stream orphan thread ki tarah chalta na rahe."""
        self.cameras = [c for c in self.cameras if c["id"] != camera_id]
        w = self.workers.pop(camera_id, None)
        if w:
            w.stop()

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