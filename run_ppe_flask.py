import io
import queue
import re
import socket
import struct
import threading
import tempfile
import cv2
import requests
from ultralytics import YOLO
import time
import os
import numpy as np # <--- YENİ: Gelen binary resmi OpenCV'ye çevirmek için eklendi
from datetime import datetime, timezone
from flask import Flask, Response, jsonify, request
from flask_cors import CORS
from flask_sock import Sock
from gtts import gTTS
from playsound import playsound

# ======================================================
# 1. FLASK SUNUCU TANIMLARI VE SİBER GÜVENLİK AYARLARI
# ======================================================
app = Flask(__name__)
CORS(app)
sock = Sock(app)

# --- Kamera: ws (varsayilan) | post | stream ---
PPE_CAMERA_MODE = os.environ.get("PPE_CAMERA_MODE", "ws").strip().lower()
PPE_STREAM_URL = os.environ.get("PPE_STREAM_URL", "http://192.168.43.94:81/stream").strip()

# --- POST modu icin (ESP32 kare gonderirse) ---
GIZLI_KEY = os.environ.get("PPE_API_KEY", "fabrika_ortak_gizli_key_123")
KABUL_EDILEBILIR_GECIKME = int(os.environ.get("PPE_TIMESTAMP_MAX_SKEW", "5"))
PPE_SHOW_WINDOW = os.environ.get("PPE_SHOW_WINDOW", "0") == "1"
POST_PROCESS_ASYNC = os.environ.get("PPE_POST_ASYNC", "1") == "1"
PPE_IMGSZ = int(os.environ.get("PPE_IMGSZ", "416"))
PPE_JPEG_QUALITY = int(os.environ.get("PPE_JPEG_QUALITY", "72"))
PPE_STREAM_FPS = float(os.environ.get("PPE_STREAM_FPS", "15"))
PPE_MAX_DISPLAY_W = int(os.environ.get("PPE_MAX_DISPLAY_W", "640"))

current_ppe_status = {
    "person_detected": False,
    "hardhat_warning": False,
    "safety_vest_warning": False,
    "mask_warning": False,
    "updated_at": None,
}
_status_lock = threading.Lock()

_latest_jpeg = None
_frame_lock = threading.Lock()
_has_frame = False
_frame_version = 0

_yolo_q = queue.Queue(maxsize=1)
_yolo_worker_lock = threading.Lock()
_yolo_worker_started = False

# Global YOLO modeli ve Stabilizer tanımları (Thread'ler arası ortak kullanım için)
yolo_model = None
model_lock = threading.Lock()


def _set_latest_jpeg_bytes(data: bytes) -> None:
    """Ham JPEG — aninda web/MJPEG onizleme."""
    global _latest_jpeg, _has_frame, _frame_version
    if not data:
        return
    with _frame_lock:
        _latest_jpeg = data
        _has_frame = True
        _frame_version += 1


def _set_latest_frame(bgr_image) -> None:
    """YOLO cizimli kare — Flutter / web ortam izleme."""
    global _latest_jpeg, _has_frame, _frame_version
    if bgr_image is None:
        return
    h, w = bgr_image.shape[:2]
    if w > PPE_MAX_DISPLAY_W:
        nh = int(h * PPE_MAX_DISPLAY_W / w)
        bgr_image = cv2.resize(
            bgr_image, (PPE_MAX_DISPLAY_W, nh), interpolation=cv2.INTER_AREA
        )
    ok, buf = cv2.imencode(
        ".jpg",
        bgr_image,
        [int(cv2.IMWRITE_JPEG_QUALITY), PPE_JPEG_QUALITY],
    )
    if not ok:
        return
    with _frame_lock:
        _latest_jpeg = buf.tobytes()
        _has_frame = True
        _frame_version += 1


def _yolo_worker_loop() -> None:
    while True:
        frame = _yolo_q.get()
        if frame is None:
            continue
        try:
            _process_frame(frame)
        except Exception as e:
            print(f"YOLO kare hata: {e}", flush=True)


def _ensure_yolo_worker() -> None:
    global _yolo_worker_started
    with _yolo_worker_lock:
        if _yolo_worker_started:
            return
        _yolo_worker_started = True
        threading.Thread(target=_yolo_worker_loop, daemon=True).start()


def _enqueue_yolo_frame(frame) -> None:
    """Eski bekleyen kareyi at — her zaman en guncel kare islenir."""
    _ensure_yolo_worker()
    try:
        _yolo_q.put_nowait(frame)
    except queue.Full:
        try:
            _yolo_q.get_nowait()
        except queue.Empty:
            pass
        try:
            _yolo_q.put_nowait(frame)
        except queue.Full:
            pass


def _guess_lan_ip() -> str:
    """Yerel ag IP (ESP32 icin ws:// adresi)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def _ws_connect_hint(port: int) -> str:
    ip = _guess_lan_ip()
    return (
        f"ws://{ip}:{port}/ws/camera"
        f"?api_key={GIZLI_KEY}&ts=<UNIX_SN>&device_id=esp32cam"
    )


def _verify_device_auth(api_key: str | None, client_time: str | None) -> tuple[bool, str]:
    """API key + zaman damgasi (WebSocket handshake / POST)."""
    if api_key != GIZLI_KEY:
        return False, "Yetkisiz cihaz"
    if not client_time:
        return False, "Zaman damgasi eksik"
    try:
        fark = abs(int(time.time()) - int(client_time))
        if fark > KABUL_EDILEBILIR_GECIKME:
            return False, f"Zaman asimi ({fark}s)"
    except ValueError:
        return False, "Gecersiz zaman"
    return True, ""


def _ingest_jpeg_bytes(jpeg: bytes) -> bool:
    """Ham JPEG yayinla + YOLO kuyrugu."""
    if len(jpeg) < 200:
        return False
    _set_latest_jpeg_bytes(jpeg)
    frame = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        return False
    if POST_PROCESS_ASYNC:
        _enqueue_yolo_frame(frame.copy())
    else:
        _process_frame(frame)
    return True


def _parse_ws_payload(data: bytes) -> tuple[int | None, bytes]:
    """[4 byte seq][JPEG] veya ham JPEG (FF D8)."""
    if len(data) >= 2 and data[0] == 0xFF and data[1] == 0xD8:
        return None, data
    if len(data) > 4:
        body = data[4:]
        if len(body) >= 2 and body[0] == 0xFF and body[1] == 0xD8:
            return struct.unpack(">I", data[:4])[0], body
    return None, data


def _status_json():
    with _status_lock:
        return dict(current_ppe_status)


@app.route("/api/status", methods=["GET"])
def get_status():
    return jsonify(_status_json()), 200


@app.route("/api/ppe/<user_id>", methods=["GET"])
def get_ppe(user_id):
    """Flutter dashboard — ayni durum verisi."""
    return jsonify(_status_json()), 200


@app.route("/api/frame", methods=["GET"])
def api_frame():
    """Son YOLO karesi (JPEG) — mobil ortam izleme."""
    with _frame_lock:
        data = _latest_jpeg
        ready = _has_frame
    if not ready or not data:
        return jsonify({"error": "Kamera karesi henuz yok"}), 503
    return Response(data, mimetype="image/jpeg")


@app.route("/video_feed")
def video_feed():
    """MJPEG — tarayici icin canli yayin."""
    interval = 1.0 / max(1.0, PPE_STREAM_FPS)

    def generate():
        last_ver = -1
        while True:
            with _frame_lock:
                data = _latest_jpeg
                ver = _frame_version
            if data and ver != last_ver:
                last_ver = ver
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + data + b"\r\n"
                )
            time.sleep(interval)

    return Response(
        generate(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


# ======================================================
# 🔒 YENİ: ESP32-CAM'DEN GELEN GÖRÜNTÜ POST ENDPOINT'İ
# ======================================================
@app.route("/camera-data", methods=["POST"])
def receive_camera_data():
    global yolo_model
    
    # 1. ADIM: Kapı Güvenlik Kontrolleri (HTTP Headers)
    api_key = request.headers.get('X-API-Key')
    client_time = request.headers.get('X-Timestamp')
    
    # Parola Doğrulama
    if api_key != GIZLI_KEY:
        print("[SİBER ALARM]: Yetkisiz cihaz sızma girişimi engellendi!", flush=True)
        return jsonify({"status": "REJECTED", "message": "Yetkisiz cihaz!"}), 401
        
    # Zaman Damgası Kontrolü
    if not client_time:
        return jsonify({"status": "REJECTED", "message": "Zaman damgası eksik!"}), 400
        
    # Replay Attack (Yeniden Oynatma) Süre Kontrolü
    try:
        sunucu_saati = int(time.time())
        cihaz_saati = int(client_time)
        fark = abs(sunucu_saati - cihaz_saati)
        
        if fark > KABUL_EDILEBILIR_GECIKME:
            print(f"[SİBER ALARM]: Gecikmiş paket reddedildi! Fark: {fark} sn (Replay Attack şüphesi).", flush=True)
            return jsonify({"status": "ATTACK_DETECTED", "message": "Zaman aşımı! Paket güncel değil."}), 403
    except ValueError:
        return jsonify({"status": "REJECTED", "message": "Geçersiz zaman formatı!"}), 400

    # 2. ADIM: Güvenlik Geçildi, Görüntüyü Al ve OpenCV formatına çevir
    file_bytes = np.frombuffer(request.data, np.uint8)
    frame = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)
    
    if frame is None:
        return jsonify({"status": "ERROR", "message": "Görüntü çözülemedi!"}), 400

    # Ham JPEG'i hemen yayinla; YOLO arka planda (kuyruk = tek guncel kare)
    raw_jpeg = bytes(request.data)
    if len(raw_jpeg) > 200:
        _set_latest_jpeg_bytes(raw_jpeg)

    if POST_PROCESS_ASYNC:
        _enqueue_yolo_frame(frame.copy())
    else:
        _process_frame(frame)
    return jsonify({"status": "SUCCESS", "message": "Kare güvenle işlendi."}), 200


@sock.route("/ws/camera")
def ws_camera(ws):
    """
    ESP32 WebSocket — handshake: ?api_key=&ts=&device_id=
    Binary: [4 byte seq][JPEG] veya ham JPEG.
    """
    api_key = request.args.get("api_key") or request.args.get("X-API-Key")
    client_time = request.args.get("ts") or request.args.get("X-Timestamp")
    device_id = request.args.get("device_id", "esp32")

    ok, err = _verify_device_auth(api_key, client_time)
    if not ok:
        print(f"[WS RED] {device_id}: {err}", flush=True)
        try:
            ws.send(f'{{"status":"REJECTED","message":"{err}"}}')
        except Exception:
            pass
        return

    print(f"[WS OK] {device_id} baglandi", flush=True)
    ws.send('{"status":"AUTH_OK"}')
    last_seq = -1
    frames = 0

    while True:
        try:
            data = ws.receive()
        except Exception as e:
            print(f"[WS] {device_id} receive hata: {e}", flush=True)
            break
        if data is None:
            break
        if isinstance(data, str):
            continue
        seq, jpeg = _parse_ws_payload(data)
        if seq is not None and seq <= last_seq:
            continue
        if seq is not None:
            last_seq = seq
        if _ingest_jpeg_bytes(jpeg):
            frames += 1
            if frames == 1 or frames % 30 == 0:
                print(f"[WS] {device_id} kare #{frames}", flush=True)

    print(f"[WS] {device_id} kapandi ({frames} kare)", flush=True)


@app.route("/api/speak", methods=["POST"])
def api_speak():
    payload = request.get_json(silent=True) or {}
    text = (payload.get("text") or "").strip()
    if not text:
        return jsonify({"error": "text gerekli"}), 400
    buf = io.BytesIO()
    gTTS(text=text[:400], lang="tr", tld="com.tr", slow=True).write_to_fp(buf)
    return Response(buf.getvalue(), mimetype="audio/mpeg")


def _ppe_sesli_mesaj(status: dict) -> str:
    eksikler = []
    if status.get("hardhat_warning"):
        eksikler.append("baret")
    if status.get("safety_vest_warning"):
        eksikler.append("yelek")
    if status.get("mask_warning"):
        eksikler.append("maske")
    if not eksikler:
        return "Ekipmanlar tamam. İyi çalışmalar."
    return "Koruyucu ekipman eksik. Lütfen takın."


PC_SPEAK_ENABLED = os.environ.get("PPE_PC_SPEAK", "1") == "1"

PERSON_ON_FRAMES = int(os.environ.get("PPE_PERSON_ON", "3"))
PERSON_OFF_FRAMES = int(os.environ.get("PPE_PERSON_OFF", "10"))
PERSON_HOLD_SEC = float(os.environ.get("PPE_PERSON_HOLD", "2.5"))
WARN_ON_FRAMES = int(os.environ.get("PPE_WARN_ON", "2"))
WARN_OFF_FRAMES = int(os.environ.get("PPE_WARN_OFF", "8"))
WARN_HOLD_SEC = float(os.environ.get("PPE_WARN_HOLD", "4"))
FRAME_SKIP = max(1, int(os.environ.get("PPE_FRAME_SKIP", "2")))


class PpeStabilizer:
    def __init__(self):
        self._person_on = 0
        self._person_off = 0
        self._last_person_ts = 0.0
        self._warn_on = {"hardhat": 0, "vest": 0, "mask": 0}
        self._warn_off = {"hardhat": 0, "vest": 0, "mask": 0}
        self._warn_hold_until = {"hardhat": 0.0, "vest": 0.0, "mask": 0.0}
        self.stable = {
            "person_detected": False,
            "hardhat_warning": False,
            "safety_vest_warning": False,
            "mask_warning": False,
        }

    def update(self, raw: dict) -> dict:
        now = time.time()
        raw_person = bool(raw.get("person_detected"))

        if raw_person:
            self._person_on += 1
            self._person_off = 0
            self._last_person_ts = now
        else:
            self._person_off += 1
            self._person_on = 0

        person = self.stable["person_detected"]
        if not person:
            if self._person_on >= PERSON_ON_FRAMES:
                person = True
        else:
            lost_long = self._person_off >= PERSON_OFF_FRAMES
            hold_expired = (now - self._last_person_ts) > PERSON_HOLD_SEC
            if lost_long and hold_expired:
                person = False

        if (now - self._last_person_ts) < PERSON_HOLD_SEC:
            person = True

        warn_map = (
            ("hardhat_warning", "hardhat", "hardhat_warning"),
            ("safety_vest_warning", "vest", "safety_vest_warning"),
            ("mask_warning", "mask", "mask_warning"),
        )
        stable = {"person_detected": person}
        for stable_key, short, raw_key in warn_map:
            raw_warn = bool(raw.get(raw_key))
            if raw_warn:
                self._warn_on[short] += 1
                self._warn_off[short] = 0
                if self._warn_on[short] >= WARN_ON_FRAMES:
                    self.stable[stable_key] = True
                    self._warn_hold_until[short] = now + WARN_HOLD_SEC
            else:
                self._warn_off[short] += 1
                self._warn_on[short] = 0

            val = self.stable[stable_key]
            if val:
                if now < self._warn_hold_until[short]:
                    val = True
                elif self._warn_off[short] >= WARN_OFF_FRAMES:
                    val = False
            stable[stable_key] = val

        if not person:
            for stable_key, short, _ in warn_map:
                if now >= self._warn_hold_until[short]:
                    stable[stable_key] = False

        self.stable.update(stable)
        return dict(self.stable)


_stabilizer = PpeStabilizer()


def _stream_url_candidates() -> list[str]:
    """ESP32-CAM icin denenecek adresler (ilk acilan kullanilir)."""
    urls: list[str] = []
    if PPE_STREAM_URL:
        urls.append(PPE_STREAM_URL)
    extra = os.environ.get("PPE_STREAM_URLS", "").strip()
    if extra:
        urls.extend(u.strip() for u in extra.split(",") if u.strip())

    m = re.search(r"https?://([^/]+)", PPE_STREAM_URL or "")
    if m:
        host = m.group(1)
        ip = host.split(":")[0]
        for u in (
            f"http://{host}/stream",
            f"http://{host}/capture",
            f"http://{ip}/stream",
            f"http://{ip}/capture",
            f"http://{ip}:80/stream",
            f"http://{ip}:80/capture",
        ):
            if u not in urls:
                urls.append(u)

    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _parse_camera_host() -> tuple[str, int]:
    m = re.search(r"https?://([^/]+)", PPE_STREAM_URL or "")
    if not m:
        return "", 81
    host = m.group(1)
    if ":" in host:
        ip, port_s = host.rsplit(":", 1)
        try:
            return ip, int(port_s)
        except ValueError:
            return host, 81
    return host, 80


def _tcp_port_open(ip: str, port: int, timeout: float = 2.0) -> bool:
    if not ip or port <= 0:
        return False
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def _log_camera_network_hint():
    ip, port = _parse_camera_host()
    if not ip:
        return
    http_open = _tcp_port_open(ip, port, timeout=1.5)
    print(f"Kamera IP: {ip} | HTTP port {port} acik: {http_open}", flush=True)
    if not http_open:
        print(
            "HATA: Cihaz agda olabilir ama HTTP sunucusu kapali.\n"
            "  - ESP32-CAM kodunda stream/capture sunucusu calisiyor mu?\n"
            "  - Seri monitorden IP ve 'camera ready' mesajini kontrol edin\n"
            "  - Tarayicida acin: http://" + ip + ":" + str(port) + "/stream\n"
            "  - Firmware sadece POST gonderiyorsa: PPE_CAMERA_MODE=post",
            flush=True,
        )


def _read_frame_http(url: str):
    """Tek kare JPEG (capture endpoint)."""
    try:
        r = requests.get(url, timeout=5)
        if r.status_code != 200 or not r.content:
            return None
        arr = np.frombuffer(r.content, np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)
    except Exception as e:
        print(f"HTTP kare alinamadi ({url}): {e}", flush=True)
        return None


def _open_esp32_camera():
    """OpenCV ile ESP32-CAM akisi ac."""
    _log_camera_network_hint()
    for url in _stream_url_candidates():
        print(f"Kamera deneniyor: {url}", flush=True)
        try:
            r = requests.get(url, stream=True, timeout=4)
            if r.status_code != 200:
                print(f"  HTTP {r.status_code}", flush=True)
                r.close()
                continue
            r.close()
        except Exception as e:
            print(f"  Baglanti yok: {e}", flush=True)
            continue

        cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
        if not cap.isOpened():
            cap.release()
            continue
        ret, probe = cap.read()
        if ret and probe is not None and probe.size > 0:
            print(f"Kamera baglandi: {url}", flush=True)
            return cap, url
        cap.release()
        print(f"Kare alinamadi: {url}", flush=True)
    return None, None


def _process_frame(frame) -> None:
    """Tek kare: YOLO + durum + onizleme."""
    global yolo_model
    if frame is None or yolo_model is None:
        return
    conf = float(os.environ.get("PPE_CONF", "0.5"))
    iou = float(os.environ.get("PPE_IOU", "0.5"))
    device = int(os.environ.get("PPE_DEVICE", "0"))
    h, w = frame.shape[:2]
    infer = frame
    if w > PPE_IMGSZ:
        scale = PPE_IMGSZ / w
        infer = cv2.resize(
            frame,
            (PPE_IMGSZ, int(h * scale)),
            interpolation=cv2.INTER_AREA,
        )
    with model_lock:
        results = yolo_model.predict(
            source=infer,
            conf=conf,
            iou=iou,
            imgsz=PPE_IMGSZ,
            device=device,
            verbose=False,
        )
    annotated = results[0].plot()
    _set_latest_frame(annotated)
    raw = _parse_yolo_frame(results)
    stable = _stabilizer.update(raw)
    _publish_status(stable)
    if PPE_SHOW_WINDOW:
        cv2.imshow("PPE Kamera Yayini", annotated)
        cv2.waitKey(1)


def run_snapshot_poll():
    """Port acik degilse veya sadece /capture varsa — saniyede bir JPEG."""
    urls = [u for u in _stream_url_candidates() if "capture" in u or u.endswith("/")]
    if not urls:
        urls = _stream_url_candidates()
    print(f"Kamera modu: snapshot poll | {urls[0]}", flush=True)
    _log_camera_network_hint()
    frame_no = 0
    while True:
        for url in urls:
            frame = _read_frame_http(url)
            if frame is not None:
                frame_no += 1
                if frame_no % FRAME_SKIP == 0:
                    _process_frame(frame)
                break
        else:
            time.sleep(3)
            continue
        time.sleep(max(0.15, float(os.environ.get("PPE_SNAPSHOT_INTERVAL", "0.35"))))


def run_yolo_stream():
    """ESP32-CAM MJPEG/stream — surekli okuma."""
    print(f"Kamera modu: stream | hedef: {PPE_STREAM_URL}", flush=True)
    cap = None
    active_url = None
    frame_no = 0
    snapshot_fallback = os.environ.get("PPE_SNAPSHOT_FALLBACK", "1") == "1"

    while True:
        if cap is None or not cap.isOpened():
            if cap is not None:
                cap.release()
            cap, active_url = _open_esp32_camera()
            if cap is None:
                if snapshot_fallback:
                    print("MJPEG acilmadi -> snapshot moduna geciliyor...", flush=True)
                    run_snapshot_poll()
                    return
                print(
                    "ESP32-CAM acilmadi.\n"
                    "  PPE_STREAM_URL=http://KAMERA_IP:81/stream\n"
                    "  Tarayicida ayni adresi deneyin.\n"
                    "  Sadece POST varsa: PPE_CAMERA_MODE=post",
                    flush=True,
                )
                time.sleep(3)
                continue

        ret, frame = cap.read()
        if not ret or frame is None:
            print(f"Kare okunamadi ({active_url}), yeniden baglaniliyor...", flush=True)
            cap.release()
            cap = None
            time.sleep(0.5)
            continue

        frame_no += 1
        if frame_no % FRAME_SKIP == 0:
            _process_frame(frame)
        elif frame_no % (FRAME_SKIP * 3) == 0:
            _set_latest_frame(frame)


def run_flask():
    port = int(os.environ.get("PPE_PORT", "5002"))
    lan_ip = _guess_lan_ip()
    print(f"Flask PPE API: http://{lan_ip}:{port}/api/status", flush=True)
    print(f"Kamera JPEG: http://{lan_ip}:{port}/api/frame", flush=True)
    print(f"Kamera MJPEG: http://{lan_ip}:{port}/video_feed", flush=True)
    mode = PPE_CAMERA_MODE
    if mode in ("ws", "websocket"):
        print("Kamera modu: WebSocket (yerel ag, ngrok yok)", flush=True)
        print(f"ESP32 adresi: {_ws_connect_hint(port)}", flush=True)
    elif mode == "post":
        print(f"Kamera modu: POST http://{lan_ip}:{port}/camera-data", flush=True)
    else:
        print(f"Kamera modu: stream ({PPE_STREAM_URL})", flush=True)
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


# ======================================================
# 2. AKILLI SES MOTORU VE DURUM HAFIZASI
# ======================================================
last_announcement_time = 0.0
REMINDER_COOLDOWN = float(os.environ.get("PPE_ALERT_SEC", "10"))
_speech_busy = False
_speech_lock = threading.Lock()


def _speak_worker(text):
    global _speech_busy
    path = None
    try:
        fd, path = tempfile.mkstemp(suffix=".mp3", prefix="anons_")
        os.close(fd)
        gTTS(text=text, lang="tr", tld="com.tr", slow=True).save(path)
        playsound(path, block=True)
    except Exception as e:
        print(f"Ses çalma hatası: {e}", flush=True)
    finally:
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
        with _speech_lock:
            _speech_busy = False


def tetikle_akilli_anons(status):
    global last_announcement_time, _speech_busy

    if not PC_SPEAK_ENABLED or not status.get("person_detected"):
        return

    now = time.time()
    with _speech_lock:
        if _speech_busy or (now - last_announcement_time) < REMINDER_COOLDOWN:
            return
        _speech_busy = True
        last_announcement_time = now

    sesli_mesaj = _ppe_sesli_mesaj(status)
    print(f"[SESLİ ANONS]: {sesli_mesaj}", flush=True)
    threading.Thread(target=_speak_worker, args=(sesli_mesaj,), daemon=True).start()


# ======================================================
# 3. YOLO KARE ANALİZ YARDIMCISI
# ======================================================
def _parse_yolo_frame(results) -> dict:
    status = {
        "person_detected": False,
        "hardhat_warning": False,
        "safety_vest_warning": False,
        "mask_warning": False,
    }
    if not results or not results[0].boxes:
        return status

    for box in results[0].boxes:
        class_id = int(box.cls[0])
        class_name = results[0].names[class_id]
        if class_name == "Person":
            status["person_detected"] = True
        elif class_name == "NO-Hardhat":
            status["hardhat_warning"] = True
        elif class_name == "NO-Safety Vest":
            status["safety_vest_warning"] = True
        elif class_name == "NO-Mask":
            status["mask_warning"] = True
    return status


def _publish_status(stable: dict):
    stable["updated_at"] = datetime.now(timezone.utc).isoformat()
    stable["speech_text"] = (
        _ppe_sesli_mesaj(stable) if stable.get("person_detected") else ""
    )
    with _status_lock:
        current_ppe_status.clear()
        current_ppe_status.update(stable)
    tetikle_akilli_anons(stable)


# ======================================================
# 4. ANA TETİKLEYİCİ (MAIN)
# ======================================================
if __name__ == '__main__':
    print(f"Sesli uyari: her {REMINDER_COOLDOWN:.0f} saniyede bir (PC hoparloru)", flush=True)
    print("Dashboard: stabilize edilmis /api/status (titreme azaltildi)", flush=True)
    
    # YOLO modelini ana thread'de bir kez yüklüyoruz
    print("YOLO Modeli yukleniyor...", flush=True)
    yolo_model = YOLO("best.pt")
    print("--- Akıllı Sesli PPE Takibi Başladı ---", flush=True)
    
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    time.sleep(0.8)

    if PPE_CAMERA_MODE in ("post", "ws", "websocket"):
        _ensure_yolo_worker()
        port = int(os.environ.get("PPE_PORT", "5002"))
        if PPE_CAMERA_MODE in ("ws", "websocket"):
            print("ESP32 + PC ayni Wi-Fi aginda olmali.", flush=True)
            print(f"Arduino wsHost = \"{_guess_lan_ip()}\"  wsPort = {port}", flush=True)
        else:
            print("ESP32 POST modu: /camera-data", flush=True)
        print(
            f"YOLO imgsz={PPE_IMGSZ} | yayin ~{PPE_STREAM_FPS:.0f} fps",
            flush=True,
        )
        print("Flask calisiyor — [WS OK] ve kare loglarini bekleyin.", flush=True)
        flask_thread.join()
    elif PPE_CAMERA_MODE == "snapshot":
        run_snapshot_poll()
    else:
        run_yolo_stream()