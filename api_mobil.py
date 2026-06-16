import io
import os
import re
import threading
import time

from flask import Flask, request, jsonify, Response
import requests
from gtts import gTTS

app = Flask(__name__)

DEFAULT_USER_ID = "5757a1d7-b497-4b66-b5d1-2a72e3261a73"

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I,
)

def valid_uuid(value):
    return bool(value and UUID_RE.match(str(value).strip()))

# ======================================================
# SUPABASE
# ======================================================

SUPABASE_PROJECT = "tsslkuwpqqvxxhuwttbk"

SUPABASE_BASE = f"https://{SUPABASE_PROJECT}.supabase.co/rest/v1"

SUPABASE_REST_URL = f"{SUPABASE_BASE}/sensor_data"

SUPABASE_ANON_KEY = os.environ.get(
    "SUPABASE_ANON_KEY",
    "sb_publishable_9cX7xtFcc85spzMuD2XBgQ_ro1YcEJU",
)

SUPABASE_DASHBOARD = (
    f"https://supabase.com/dashboard/project/{SUPABASE_PROJECT}/editor"
)

SUPABASE_WRITE_INTERVAL = float(
    os.environ.get("SUPABASE_WRITE_SEC", "1")
)

_http = requests.Session()

_data_lock = threading.Lock()

_last_supabase_write = 0.0

def _supabase_headers():
    return {
        "Content-Type": "application/json",
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
        "Prefer": "return=minimal",
    }

# ======================================================
# MERKEZİ VERİ
# ======================================================

combined_data = {
    "user_id": DEFAULT_USER_ID,
    "device_id": "esp32_combined_node",

    "ambient_temp": 24.0,
    "humidity": 50.0,

    "gas_level": 0.0,
    "gas_level2": 0.0,

    "gas_percent": 0.0,
    "gas_percent2": 0.0,

    "flame": False,

    "heart_rate": 0.0,
    "body_temp": 0.0,

    "risk": 0,
    "status": "SAFE",

    "updated_at": time.time(),

    "last_supabase_id": None,
    "last_supabase_at": None,
}

# ======================================================
# YARDIMCI FONKSİYONLAR
# ======================================================

def parse_flame(value):

    if value is None:
        return False

    if isinstance(value, bool):
        return value

    if isinstance(value, (int, float)):
        return value != 0

    s = str(value).strip().lower()

    return s in ("1", "true", "yes", "on", "high")

def calculate_air_quality(delta):

    try:
        val = float(delta)

        score = (val / 800.0) * 100

        return max(0.0, min(100.0, round(score, 1)))

    except:
        return 0.0

def execute_risk_engine(data):

    max_risk = 0
    status = "SAFE"

    hr = float(data.get("heart_rate", 0))
    b_temp = float(data.get("body_temp", 0))
    a_temp = float(data.get("ambient_temp", 0))

    g1 = float(data.get("gas_percent", 0))
    g2 = float(data.get("gas_percent2", 0))

    flame = bool(data.get("flame", False))

    # Kritik sıcaklık + nabız
    if a_temp > 35 and b_temp > 37.5 and hr > 110:
        max_risk = max(max_risk, 90)
        status = "CRITICAL"

    elif a_temp > 30 and hr > 100:
        max_risk = max(max_risk, 50)
        status = "WARNING"

    # Gaz + hareket yok
    if (g1 > 40 or g2 > 40) and hr == 0:
        max_risk = max(max_risk, 100)
        status = "CRITICAL"

    # Yangın
    if flame and (g2 > 30 or a_temp > 40):
        max_risk = max(max_risk, 100)
        status = "FIRE DETECTED"

    elif flame:
        max_risk = max(max_risk, 75)
        status = "WARNING"

    # Aşırı nabız
    if b_temp < 37 and a_temp < 30 and hr > 130:
        max_risk = max(max_risk, 85)
        status = "CRITICAL"

    if hr > 140 or b_temp > 39:
        max_risk = max(max_risk, 95)
        status = "CRITICAL"

    return max_risk, status

def _should_write_supabase(payload):

    global _last_supabase_write

    now = time.time()

    if payload.get("flame"):
        return True

    if int(payload.get("risk", 0)) >= 75:
        return True

    return (now - _last_supabase_write) >= SUPABASE_WRITE_INTERVAL

def _write_supabase(payload):

    global _last_supabase_write

    try:

        r = _http.post(
            SUPABASE_REST_URL,
            headers=_supabase_headers(),
            json=payload,
            timeout=8,
        )

        if r.status_code not in (200, 201, 204):

            print(
                f"❌ SUPABASE {r.status_code}: {r.text}",
                flush=True
            )

            return

        _last_supabase_write = time.time()

        with _data_lock:

            combined_data["last_supabase_at"] = time.time()

        print(
            f"✅ Supabase kayıt edildi | HR={payload['heart_rate']} | Risk={payload['risk']}",
            flush=True
        )

    except Exception as e:

        print(f"❌ Supabase hata: {e}", flush=True)

# ======================================================
# DATA ENDPOINT
# ======================================================

@app.route('/upload', methods=['POST'])
def receive_data():

    global combined_data

    incoming = request.json

    if not incoming:
        return jsonify({"error": "No JSON"}), 400

    print(f"\n📥 Gelen Veri: {incoming}", flush=True)

    with _data_lock:

        # USER ID
        uid = incoming.get("user_id", DEFAULT_USER_ID)

        if valid_uuid(uid):
            combined_data["user_id"] = uid

        # DEVICE ID
        if "device_id" in incoming:
            combined_data["device_id"] = str(
                incoming["device_id"]
            )

        # HEART
        if "heart_rate" in incoming:
            combined_data["heart_rate"] = float(
                incoming["heart_rate"]
            )

        # BODY TEMP
        if "body_temp" in incoming:
            combined_data["body_temp"] = float(
                incoming["body_temp"]
            )

        # AMBIENT
        if "ambient_temp" in incoming:
            combined_data["ambient_temp"] = float(
                incoming["ambient_temp"]
            )

        # HUMIDITY
        if "humidity" in incoming:
            combined_data["humidity"] = float(
                incoming["humidity"]
            )

        # GAS 1
        if "gas_level" in incoming:

            combined_data["gas_level"] = float(
                incoming["gas_level"]
            )

            combined_data["gas_percent"] = (
                calculate_air_quality(
                    incoming["gas_level"]
                )
            )

        # GAS 2
        if "gas_level2" in incoming:

            combined_data["gas_level2"] = float(
                incoming["gas_level2"]
            )

            combined_data["gas_percent2"] = (
                calculate_air_quality(
                    incoming["gas_level2"]
                )
            )

        # FLAME
        if "flame" in incoming:
            combined_data["flame"] = parse_flame(
                incoming["flame"]
            )

        combined_data["updated_at"] = time.time()

        risk, status = execute_risk_engine(combined_data)

        combined_data["risk"] = risk
        combined_data["status"] = status

        snapshot = dict(combined_data)

    # ==================================================
    # TÜM VERİLER SUPABASE'E
    # ==================================================

    supabase_payload = {

        "user_id": snapshot["user_id"],
        "device_id": snapshot["device_id"],

        "ambient_temp": snapshot["ambient_temp"],
        "humidity": snapshot["humidity"],

        "gas_level": snapshot["gas_level"],
        "gas_level2": snapshot["gas_level2"],

        "gas_percent": snapshot["gas_percent"],
        "gas_percent2": snapshot["gas_percent2"],

        "flame": snapshot["flame"],

        "heart_rate": snapshot["heart_rate"],
        "body_temp": snapshot["body_temp"],

        "risk": snapshot["risk"],
        "status": snapshot["status"],

        "updated_at": snapshot["updated_at"],
    }

    queued = False

    if _should_write_supabase(supabase_payload):

        threading.Thread(
            target=_write_supabase,
            args=(supabase_payload,),
            daemon=True,
        ).start()

        queued = True

    return jsonify({
        "status": "ok",
        "risk": risk,
        "system": status,
        "supabase_queued": queued,
        "data": snapshot,
    })

# ======================================================
# STATUS
# ======================================================

@app.route('/api/status')
def status():

    with _data_lock:
        return jsonify(dict(combined_data))

# ======================================================
# TTS
# ======================================================

@app.route("/api/speak", methods=["GET", "POST"])
def speak():

    payload = request.get_json(silent=True) or {}

    text = (
        request.args.get("text")
        or payload.get("text")
        or ""
    ).strip()

    if not text:
        return jsonify({"error": "text gerekli"}), 400

    try:

        buf = io.BytesIO()

        gTTS(text=text[:500], lang="tr").write_to_fp(buf)

        buf.seek(0)

        return Response(
            buf.read(),
            mimetype="audio/mpeg"
        )

    except Exception as e:

        return jsonify({
            "error": str(e)
        }), 500

# ======================================================
# TEST
# ======================================================

@app.route("/api/supabase-check")
def supabase_check():

    try:

        r = _http.get(
            SUPABASE_REST_URL,
            headers=_supabase_headers(),
            params={
                "select": "*",
                "order": "created_at.desc",
                "limit": "5",
            },
            timeout=8,
        )

        return jsonify(r.json())

    except Exception as e:

        return jsonify({
            "error": str(e)
        }), 500

# ======================================================
# MAIN
# ======================================================

if __name__ == '__main__':

    print("🚀 Flask API başladı")
    print("🌐 Port: 5000")

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False,
        use_reloader=False
    )