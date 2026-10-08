from flask import render_template
from config.config import Config
from extensions import state

class LiveCameraController:

    def __init__(self):
        # Sirf config/camera settings store karein
        self.webcam_config = next((c for c in Config.CAMERAS if c["type"] == "webcam"), None)

    # @staticmethod
    def live_page(self):
        # Global state se safely data read karein
        cameras_info = state.manager.info() if state.manager else []
        return render_template("live.html", cameras=cameras_info, webcam=self.webcam_config)

# Class ka single instance (Ab import waqt DB error nahi dega)
live_controller = LiveCameraController()