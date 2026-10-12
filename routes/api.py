from flask import Blueprint
from controllers.zones.zone_controller import zone_controller
from controllers.camera.camera_controller import camera_controller
from controllers.camera.live_camera_controller import live_controller

api_bp = Blueprint('api', __name__, url_prefix='/api')

# --- Zone Routes ---
# api_bp.add_url_rule(rule='/save_zones',endpoint='live_page',view_func=zone_controller.live_page,methods=['POST'])

# api_bp.add_url_rule(rule='/get_zones',endpoint='get_zones',view_func=zone_controller.get_zones,methods=['GET'])

# --- Camera Routes ---
# api_bp.add_url_rule(rule='/cameras',endpoint='get_cameras',view_func=camera_controller.get_all,methods=['GET'])

# --- Camera API Routes ---


api_bp.add_url_rule(
    "/cameras",
    endpoint="get_cameras",
    view_func=camera_controller.get_all,
    methods=["GET"]
)

# Agar aap web page (HTML) bhi route se render karna chahte hain:
api_bp.add_url_rule(
    rule='/cameras/live',
    endpoint='live_camera_page',
    view_func=live_controller.live_page,
    methods=['GET']
)

api_bp.add_url_rule(rule='/cameras/add',endpoint='add_camera',view_func=camera_controller.add_camera,methods=['POST'])

api_bp.add_url_rule(rule='/cameras/delete/<camera_id>',endpoint='delete_camera',view_func=camera_controller.delete_camera,methods=['DELETE'])

# --- Camera Routes ---
api_bp.add_url_rule(rule='/cameras/test_connection', endpoint='test_camera_connection', view_func=camera_controller.test_connection, methods=['POST'])

# Direct instance method pass hoga:
api_bp.add_url_rule(
    rule='/save_zones',
    endpoint='save_zones',
    view_func=zone_controller.save_zones,
    methods=['POST']
)

# Agar get_zones route URL parameter ke saath hai (e.g., /get_zones/<camera_id>):
api_bp.add_url_rule(
    rule='/get_zones/<camera_id>',
    endpoint='get_zones',
    view_func=zone_controller.get_zones,
    methods=['GET']
)