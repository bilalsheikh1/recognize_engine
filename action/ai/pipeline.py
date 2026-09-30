import cv2
import numpy as np
from ultralytics import YOLO

class MultiTaskVisionPipeline:
    def __init__(self, insight_detector=None, pose_model_path="yolo26s-pose.pt"):
        # 1. InsightFace Detector (Face Attendance)
        self.face_detector = insight_detector

        # 2. YOLO Pose Model (Fall & Fight Detection)
        print(f"[INIT] Loading YOLO Pose model: {pose_model_path}")
        self.pose_model = YOLO(pose_model_path)

    def detect_fall_and_fight(self, frame):
        """Extract keypoints and bounding boxes to detect Fall/Fight"""
        results = self.pose_model(frame, conf=0.50, verbose=False)
        if not results or len(results) == 0:
            return [], []

        result = results[0]
        boxes = result.boxes
        keypoints = result.keypoints

        falls = []
        fights = []

        if boxes is None or len(boxes) == 0:
            return falls, fights

        active_person_boxes = []

        # Iterate through detected persons
        for i, box in enumerate(boxes):
            x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
            width = x2 - x1
            height = y2 - y1

            active_person_boxes.append((x1, y1, x2, y2))

            # --- FALL DETECTION LOGIC ---
            # Aspect ratio check (Width > Height * 1.3 means horizontal orientation)
            if height > 0 and (width / height) > 1.3:
                if keypoints is not None and len(keypoints) > i:
                    kps = keypoints[i].xy[0].cpu().numpy()
                    if len(kps) > 0:
                        head_y = kps[0][1]  # Nose/Head keypoint Y coordinate
                        # Agar head center/bottom vertical position ke pass ho
                        if head_y > (y1 + height * 0.4):
                            falls.append((x1, y1, x2, y2))

        # --- FIGHT DETECTION LOGIC ---
        num_persons = len(active_person_boxes)
        for i in range(num_persons):
            for j in range(i + 1, num_persons):
                b1 = active_person_boxes[i]
                b2 = active_person_boxes[j]

                # Bounding box intersection
                x_left = max(b1[0], b2[0])
                y_top = max(b1[1], b2[1])
                x_right = min(b1[2], b2[2])
                y_bottom = min(b1[3], b2[3])

                if x_right > x_left and y_bottom > y_top:
                    intersection_area = (x_right - x_left) * (y_bottom - y_top)
                    b1_area = (b1[2] - b1[0]) * (b1[3] - b1[1])
                    b2_area = (b2[2] - b2[0]) * (b2[3] - b2[1])

                    min_area = float(min(b1_area, b2_area))
                    overlap_ratio = intersection_area / min_area if min_area > 0 else 0

                    # 40% se zayada overlap
                    if overlap_ratio > 0.40:
                        fight_box = (
                            min(b1[0], b2[0]),
                            min(b1[1], b2[1]),
                            max(b1[2], b2[2]),
                            max(b1[3], b2[3])
                        )
                        fights.append(fight_box)

        return falls, fights

    def process(self, frame):
        if frame is None:
            return None

        # Base Frame Copy
        annotated_frame = frame.copy()

        # STEP 1: Face Box (Green / Yellow)
        if self.face_detector is not None:
            annotated_frame = self.face_detector.process(annotated_frame)

        # STEP 2: Fall & Fight Boxes (Orange / Purple)
        falls, fights = self.detect_fall_and_fight(frame)

        # Draw Fall Boxes (ORANGE)
        for (x1, y1, x2, y2) in falls:
            cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), (0, 165, 255), 3)
            cv2.putText(
                annotated_frame,
                "ALERT: FALL DETECTED",
                (x1, max(y1 - 10, 20)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 165, 255),
                2
            )

        # Draw Fight Boxes (PURPLE)
        for (x1, y1, x2, y2) in fights:
            cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), (255, 0, 255), 3)
            cv2.putText(
                annotated_frame,
                "WARNING: FIGHT/COLLISION",
                (x1, max(y1 - 10, 20)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 0, 255),
                2
            )

        return annotated_frame