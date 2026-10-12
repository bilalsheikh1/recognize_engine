# Face Attendance (Flask + SocketIO + InsightFace + ChromaDB + MySQL)

## Setup

1. **Python 3.10 / 3.11** venv banayein aur install karein:
   ```bash
   python -m venv venv
   venv\Scripts\activate          # Linux/Mac: source venv/bin/activate
   pip install -r requirements.txt
   ```
   Windows par `insightface` build ke liye *Microsoft C++ Build Tools* chahiye hote hain.
2. **MySQL** chal raha ho. `.env.example` ko `.env` copy karein aur DB user/password + `ADMIN_KEY` set karein.
   Database `face_attendance` app khud bana leti hai, tables bhi (`db.create_all()`).
3. `config/config.py` mein **`CAMERAS` array** edit karein (CCTV RTSP urls + 1 webcam entry).
   Testing ke liye `source` mein video file path ya local camera index (`0`) bhi chal jata hai.
4. Run:
   ```bash
   python app.py
   ```
   Pehli baar `buffalo_l` model (~280 MB) `~/.insightface` mein download hoga.
5. Browser: `http://localhost:5000`

> Browser webcam sirf **localhost** ya **HTTPS** par chalta hai. Doosre PC se kholna ho to:
> `openssl req -x509 -newkey rsa:2048 -nodes -keyout key.pem -out cert.pem -days 365 -subj "/CN=localhost"`
> phir `.env` mein `SSL_CERT=cert.pem` aur `SSL_KEY=key.pem`.

## Pages

| URL | Kaam |
|---|---|
| `/` | Webcam attendance + saare CCTV live feeds + recent events |
| `/register` | Employee register (6 frames capture), list, delete |
| `/logs` | System logs (filter + live), Attendance (date wise), Unknown faces (visit count) |

## Architecture

- **Sockets:** `/webcam` (browser -> server frames, register), `/cctv` (server -> browser CCTV frames), `/events` (live logs). Attendance aur registration REST se nahi, sirf socket se.
- **Camera array:** `CAMERAS` mein jitni entries, utne cameras. Har `cctv` entry = 2 threads (reader + processor). `webcam` entry = browser socket source.
- **Embeddings:** InsightFace `buffalo_l`, 512-dim, L2-normalised. ChromaDB mein cosine search.
- **Attendance:** `CONFIRM_FRAMES` (2) qareebi frames mein match ho tab hi mark. Din ki pehli detection = check-in, 30 min baad dobara dikha to check-out (last seen) update.
- **Unknown:** achi quality ka unknown face `unknown_faces` table + snapshot mein save. Same banda `UNKNOWN_VISIT_GAP` (60s) ghayab rehne ke baad wapas aaye to visit count +1.
- **Duplicate registration:** naya face vector DB mein search hota hai, similarity >= `DUPLICATE_THRESHOLD` ho to reject (aur `emp_code` unique hai).
- **Failures:** camera offline/online, DB errors, socket exceptions sab `system_logs` table + `logs/app.log` mein. CCTV stream toote to auto-reconnect.

## Accuracy tuning

Accuracy camera quality par depend karti hai — koi library 95-99.9% ki guarantee nahi de sakti. Behtar result ke liye:

- Face frame mein kam az kam ~80-100 px ho (camera dur ho to main stream use karein, sub-stream nahi).
- Registration achi roshni mein karein, 5-6 samples (app khud quality check karti hai).
- `MATCH_THRESHOLD` badhayein (0.55-0.60) = false accept kam, magar kabhi kabhi real banda miss ho sakta hai.
- Apne camera ka test karein: registered logon ki `sim` values dekhein (live page par dikhti hain) aur threshold un ke hisab se set karein.

### Walking / moving banda recognize nahi ho raha

Normal issue hai: motion-blur se face detection/embedding quality gir jati hai aur banda FOV se nikalne se pehle
`CONFIRM_FRAMES` poora nahi ho pata. Ye tuning ab `config/config.py` mein already ki hui hai, apne camera ke
hisab se adjust karein:

- `PROCESS_INTERVAL` (0.15s ~ 6-7 fps) — kam karein to CCTV zyada frames process karegi, walking banda ke pass
  hone ke waqt match milne ke zyada chances banenge (CPU load zyada ho to 0.20-0.25 tak wapas barha sakte hain).
- `FAST_MATCH_THRESHOLD` (0.62) — kisi single frame mein sim isse upar ho (bohot confident match) to
  `CONFIRM_FRAMES` ka wait kiye bagair turant attendance mark ho jati hai. Yehi sabse zyada madad karta hai jab
  banda tez chal raha ho aur sirf 1 hi achi frame milti ho.
- `MIN_DET_SCORE` / `MIN_FACE_PX` (0.50 / 45px) — relax kiye gaye taake thora blur ya dur wala face bhi matching
  tak pahunche (unknown-face recording ke liye `UNKNOWN_MIN_DET_SCORE` / `UNKNOWN_MIN_FACE_PX` sakht hi rahe
  hain, taake junk unknown records na banein).
- `STREAK_WINDOW` (4.0s) — 2 confirm-frames ab 4 second ki window mein bhi match ho sakte hain (pehle 3s).
- Phir bhi miss ho raha ho to: camera ka shutter speed/FPS check karein (slow shutter = zyada motion blur), aur
  registration ke waqt employee ke 1-2 samples us distance se bhi le lein jahan se woh aksar walk karte hain —
  sirf close-up samples se walking-distance par similarity kam milti hai.

## Production notes

- `ADMIN_KEY` zaroor badlein; logs/live pages par login bhi lagayein.
- Ye single-process app hai (threads share memory). Ek se zyada gunicorn workers mat chalayein.
- Employee delete karne par uski attendance rows bhi delete hoti hain.
