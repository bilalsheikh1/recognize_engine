# AI-Powered Face Attendance System

**Flask + Socket.IO + InsightFace + ChromaDB + MySQL + AI Computer Vision**

An AI-powered face attendance and CCTV monitoring system that uses **computer vision and deep-learning-based face recognition** to identify registered employees, track attendance, detect unknown visitors, and monitor multiple live camera feeds.

## Key AI Features

* **AI Face Detection** using InsightFace
* **Deep-learning-based Face Recognition**
* **512-dimensional Face Embeddings**
* **Cosine Similarity Search** using ChromaDB
* **Multi-frame AI verification** to reduce false matches
* **AI-based Unknown Face Detection**
* **Duplicate Face Detection** during employee registration
* **Automatic Attendance Recognition**
* **Unknown Visitor Tracking and Visit Counting**
* **Real-time AI processing of webcam and CCTV streams**
* **Automatic CCTV stream reconnection**
* **AI-ready architecture for future features such as face liveness detection, person detection, gender detection, and action/activity detection**

---

## Setup

1. **Create a Python 3.10 / 3.11 virtual environment and install dependencies:**

   ```bash
   python -m venv venv
   venv\Scripts\activate          # Linux/Mac: source venv/bin/activate
   pip install -r requirements.txt
   ```

   On Windows, **Microsoft C++ Build Tools** may be required to build `insightface`.

2. **Make sure MySQL is running.**

   Copy `.env.example` to `.env` and configure the database username/password and `ADMIN_KEY`.

   The application automatically creates the `face_attendance` database and its required tables using `db.create_all()`.

3. **Configure cameras** in `config/config.py` by editing the `CAMERAS` array.

   Add your CCTV RTSP URLs and one webcam entry.

   For testing, the `source` field can also use:

   * A video file path
   * A local camera index such as `0`

4. **Run the application:**

   ```bash
   python app.py
   ```

   On the first run, the **InsightFace `buffalo_l` AI model (~280 MB)** will be downloaded to:

   ```text
   ~/.insightface
   ```

5. **Open the application:**

   ```text
   http://localhost:5000
   ```

> **Browser Webcam Requirement:**
> Browser webcam access works only on `localhost` or over **HTTPS**.
>
> If you need to access the application from another PC, generate a self-signed SSL certificate:
>
> ```bash
> openssl req -x509 -newkey rsa:2048 -nodes -keyout key.pem -out cert.pem -days 365 -subj "/CN=localhost"
> ```
>
> Then configure the following values in `.env`:
>
> ```env
> SSL_CERT=cert.pem
> SSL_KEY=key.pem
> ```

## Pages

| URL         | Description                                                                                             |
| ----------- | ------------------------------------------------------------------------------------------------------- |
| `/`         | AI-powered webcam attendance, all CCTV live feeds, and recent events                                    |
| `/register` | Employee registration with AI face capture, 6-frame enrollment, employee list, and delete functionality |
| `/logs`     | System logs with filtering and live updates, date-wise attendance, and unknown-face visit counts        |

## AI Architecture

### 1. AI Face Detection

The system uses **InsightFace**, a deep-learning-based computer vision framework, to detect faces from webcam and CCTV frames.

The AI pipeline processes incoming frames and identifies faces before performing recognition.

### 2. Face Recognition

For every detected face, the AI model generates a **512-dimensional face embedding**.

These embeddings represent the facial characteristics of a person and are used for identity matching.

Embeddings are:

* Generated using InsightFace `buffalo_l`
* 512-dimensional
* L2-normalized
* Stored in ChromaDB
* Compared using cosine similarity

### 3. AI Identity Matching

The system compares the detected face embedding against registered employee embeddings in ChromaDB.

If the similarity score passes the configured `MATCH_THRESHOLD`, the employee can be recognized.

To reduce false matches, the system uses **multi-frame confirmation** instead of relying on a single frame.

`CONFIRM_FRAMES` is set to `2` by default.

### 4. AI Attendance Detection

Once an employee is successfully verified by the AI system:

* The first detection of the day is recorded as **check-in**.
* If the employee is detected again after 30 minutes, the **check-out / last-seen time** is updated.
* Multiple frames are used for confirmation before attendance is recorded.

### 5. AI Unknown Face Detection

When the AI detects a face that does not match any registered employee, it can classify it as an **unknown face**.

High-quality unknown faces are stored in the `unknown_faces` table along with a snapshot.

If the same unknown person disappears for `UNKNOWN_VISIT_GAP` (60 seconds) and returns, their visit count is increased by `1`.

### 6. AI Duplicate Registration Detection

During employee registration, the new face embedding is compared against existing employee embeddings.

If the similarity is greater than or equal to `DUPLICATE_THRESHOLD`, the system rejects the registration to prevent the same person from being registered multiple times.

`emp_code` is also required to be unique.

---

## Real-Time AI Processing

The system supports real-time processing of:

* Browser webcam
* CCTV RTSP streams
* Multiple cameras
* Face detection
* Face recognition
* Attendance verification
* Unknown face detection
* Live events and system logs

Each CCTV camera uses two processing threads:

```text
CCTV Camera
     ↓
Reader Thread
     ↓
Video Frames
     ↓
AI Processing Thread
     ↓
Face Detection
     ↓
Face Embedding
     ↓
ChromaDB Similarity Search
     ↓
Employee / Unknown
     ↓
Attendance / Event
     ↓
Browser Dashboard
```

---

## Accuracy Tuning

Face recognition accuracy depends heavily on camera quality, lighting, face size, camera position, and image quality.

No face-recognition system can guarantee **95–99.9% accuracy** in every environment.

For better results:

* Keep the face at least **~80–100 pixels** in the camera frame.
* If the camera is far away, use the **main stream instead of the sub-stream**.
* Register employees in good lighting.
* Capture **5–6 registration samples**.
* The application performs face-quality checks automatically.
* Increase `MATCH_THRESHOLD` (for example, `0.55–0.60`) to reduce false matches.
* A higher threshold can also cause genuine employees to be missed.
* Monitor the `sim` similarity values on the live page and tune the threshold according to your actual camera environment.

---

## Production Notes

* **Change the default `ADMIN_KEY`** before deploying to production.
* Add authentication/login protection to the logs and live monitoring pages.
* This is a **single-process application** because multiple threads share in-memory state.
* Do not run multiple Gunicorn workers.
* CCTV streams automatically reconnect when a connection is interrupted.
* Camera failures, database errors, and Socket.IO exceptions are stored in `system_logs` and `logs/app.log`.
* Deleting an employee also deletes their associated attendance records.

---

## Future AI Capabilities

The architecture can be extended with additional AI computer-vision modules, including:

* **Face Liveness / Anti-Spoofing**
* **Person Detection**
* **Person Tracking**
* **Gender Detection**
* **Action Recognition**
* **Fight Detection**
* **Fall Detection**
* **Weapon Detection**
* **Intrusion Detection**
* **Restricted-Area Monitoring**
* **Real-time AI Alerts**
* **AI-based CCTV Analytics**

This makes the system suitable as a foundation for an **AI-powered CCTV and intelligent attendance platform**.
