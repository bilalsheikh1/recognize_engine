from flask import render_template, request, jsonify
from models.camera import Camera
from extensions import db, state
import cv2

class CameraController:


    def get_all(self):
        """Sare active cameras JSON format mein fetch karta hai."""
        try:
            cameras = Camera.query.all()
            return jsonify({
                "ok": True,
                "cameras": [cam.to_dict() for cam in cameras]
            }), 200
        except Exception as e:
            return jsonify({"ok": False, "message": str(e)}), 500

    def list_cameras(self):
        """Camera Listing Page Render karta hai."""
        cameras = Camera.query.all()
        return render_template("cameras.html", cameras=cameras)

    def add_camera(self):
        """Modal se camera add karne ki API."""
        try:
            data = request.get_json() or {}
            cam_id = data.get("id")
            name = data.get("name")
            cam_type = data.get("type")
            source = data.get("source")

            if not cam_id or not name:
                return jsonify({"ok": False, "message": "Camera ID aur Name required hai."}), 400

            # Check duplication
            existing = Camera.query.get(cam_id)
            if existing:
                return jsonify({"ok": False, "message": "Yeh Camera ID pehle se exist karti hai."}), 400

            new_camera = Camera(
                id=cam_id,
                name=name,
                type=cam_type,
                source=source if cam_type == "cctv" else None
            )

            db.session.add(new_camera)
            db.session.commit()

            # Server restart ka wait kiye bina turant stream start karo (CCTV worker)
            if state.manager:
                state.manager.add_camera(new_camera)

            return jsonify({"ok": True, "message": "Camera successfully add ho gaya hai."})

        except Exception as e:
            db.session.rollback()
            return jsonify({"ok": False, "message": str(e)}), 500

    def delete_camera(self, camera_id):
        """Camera delete karne ki API."""
        try:
            camera = Camera.query.get(camera_id)
            if not camera:
                return jsonify({"ok": False, "message": "Camera nahi mila."}), 404

            db.session.delete(camera)
            db.session.commit()

            if state.manager:
                state.manager.remove_camera(camera_id)

            return jsonify({"ok": True, "message": "Camera deleted."})
        except Exception as e:
            db.session.rollback()
            return jsonify({"ok": False, "message": str(e)}), 500

    def test_connection(self):
        """Webcam / CCTV stream verification endpoint"""
        try:
            data = request.get_json() or {}
            cam_type = data.get("type", "webcam")
            source = data.get("source")

            if cam_type == "cctv":
                if not source:
                    return jsonify({"ok": False, "message": "RTSP URL required"}), 400

                # Try opening RTSP stream using OpenCV
                cap = cv2.VideoCapture(source)
                success, _ = cap.read()
                cap.release()

                if success:
                    return jsonify({"ok": True, "message": "CCTV RTSP stream connected successfully!"}), 200
                else:
                    return jsonify(
                        {"ok": False, "message": "Unable to connect to RTSP stream. Check URL/Network."}), 400

            else:
                # Webcams are validated client-side via getUserMedia
                return jsonify({"ok": True, "message": "Webcam connection request ready."}), 200

        except Exception as e:
            return jsonify({"ok": False, "message": f"Connection test failed: {str(e)}"}), 500

camera_controller = CameraController()