from flask import Blueprint
# import sys
# import os
# sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from controllers.camera.live_camera_controller import live_controller


# Blueprint declare karein
web_bp = Blueprint('web', __name__)

# =========================================================
# WEB ROUTES
# =========================================================
web_bp.add_url_rule(rule='/', endpoint='live_page', view_func=live_controller.live_page, methods=['GET'])
