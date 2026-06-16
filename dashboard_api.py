"""
Safety Guard — web dashboard API + statik site.

Calistirma:
  python dashboard_api.py

Tarayici: http://127.0.0.1:5003/
API:      GET /api/dashboard/users

Port: 5003 (api_mobil=5000, run_ppe_flask=5002)
"""

import os
import re
from collections import OrderedDict
from typing import Optional

import requests
from flask import Flask, Response, jsonify, send_from_directory
from flask_cors import CORS


def _load_env_file():
    """Proje kokundeki .env dosyasini oku (service role icin)."""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.isfile(env_path):
        return
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val


_load_env_file()

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web_dashboard")

app = Flask(__name__, static_folder=WEB_DIR, static_url_path="")
CORS(app)

SUPABASE_PROJECT = os.environ.get("SUPABASE_PROJECT", "tsslkuwpqqvxxhuwttbk")
SUPABASE_BASE = f"https://{SUPABASE_PROJECT}.supabase.co/rest/v1"
SUPABASE_AUTH_URL = f"https://{SUPABASE_PROJECT}.supabase.co/auth/v1"
SUPABASE_ANON_KEY = os.environ.get(
    "SUPABASE_ANON_KEY",
    "sb_publishable_9cX7xtFcc85spzMuD2XBgQ_ro1YcEJU",
)
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
PPE_API_URL = os.environ.get("PPE_API_URL", "http://127.0.0.1:5002/api/status").strip()


def _ppe_base_url() -> str:
    """run_ppe_flask kok URL (ornek: http://127.0.0.1:5002)."""
    base = (PPE_API_URL or "http://127.0.0.1:5002/api/status").strip()
    if "/api/" in base:
        return base.split("/api/", 1)[0].rstrip("/")
    return base.rstrip("/") or "http://127.0.0.1:5002"

RISKY_STATUSES = frozenset({"WARNING", "CRITICAL", "FIRE DETECTED"})

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I,
)

_http = requests.Session()
SENSOR_SELECT = (
    "id,user_id,device_id,heart_rate,body_temp,ambient_temp,humidity,"
    "gas_level,gas_percent,gas_level2,gas_percent2,flame,risk,status,created_at"
)
HISTORY_SELECT = (
    "user_id,created_at,heart_rate,body_temp,ambient_temp,humidity,"
    "gas_percent,gas_percent2"
)
HISTORY_PER_USER = int(os.environ.get("DASHBOARD_HISTORY_POINTS", "40"))


def _headers(service=False):
    key = SUPABASE_SERVICE_KEY if service and SUPABASE_SERVICE_KEY else SUPABASE_ANON_KEY
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def _short_uid(uid: str) -> str:
    if not uid or len(uid) < 8:
        return uid or "?"
    return f"{uid[:8]}…"


def _profile_contact(row: dict) -> str:
    """Sizin tabloda e-posta `username` sutununda."""
    return (row.get("email") or row.get("username") or "").strip()


def _normalize_profile_rows(rows: list[dict]) -> list[dict]:
    out = []
    for row in rows:
        uid = str(row.get("id", "")).strip()
        if not uid:
            continue
        out.append(
            {
                "id": uid,
                "full_name": (row.get("full_name") or "").strip(),
                "email": _profile_contact(row),
            }
        )
    return out


def _fetch_all_profiles() -> list[dict]:
    """Uygulamada kayitli tum hesaplar (profiles tablosu)."""
    for select in (
        "id,full_name,username",
        "id,full_name,email",
        "id,full_name",
    ):
        r = _http.get(
            f"{SUPABASE_BASE}/profiles",
            headers=_headers(),
            params={"select": select, "order": "full_name.asc"},
            timeout=12,
        )
        if r.status_code == 200:
            return _normalize_profile_rows(r.json())
    return []


def _fetch_registered_users() -> list[dict]:
    """
    Tum auth hesaplari + isim (RPC: get_dashboard_users).
    SQL dosyasini Supabase'de bir kez calistirmaniz gerekir.
    """
    r = _http.post(
        f"{SUPABASE_BASE}/rpc/get_dashboard_users",
        headers=_headers(),
        json={},
        timeout=15,
    )
    if r.status_code != 200:
        return []
    rows = r.json()
    if not isinstance(rows, list):
        return []
    out = []
    for row in rows:
        uid = str(row.get("id", "")).strip()
        if not uid:
            continue
        out.append(
            {
                "id": uid,
                "full_name": (row.get("full_name") or "").strip(),
                "email": (row.get("email") or "").strip(),
            }
        )
    return out


def _fetch_profiles_map(user_ids: list[str]) -> dict[str, dict]:
    if not user_ids:
        return {}
    out: dict[str, dict] = {}
    chunk = 40
    for i in range(0, len(user_ids), chunk):
        part = user_ids[i : i + chunk]
        ids_csv = ",".join(part)
        for select in (
            "id,full_name,username",
            "id,full_name,email",
            "id,full_name",
        ):
            r = _http.get(
                f"{SUPABASE_BASE}/profiles",
                headers=_headers(),
                params={"select": select, "id": f"in.({ids_csv})"},
                timeout=12,
            )
            if r.status_code != 200:
                continue
            for row in _normalize_profile_rows(r.json()):
                out[row["id"]] = row
            break
    return out


def _registered_from_auth() -> list[dict]:
    """Service role ile auth'daki tum hesaplar (RPC olmadan)."""
    out = []
    for au in _fetch_auth_users():
        uid = str(au.get("id", "")).strip()
        if not uid:
            continue
        meta = au.get("user_metadata") or {}
        out.append(
            {
                "id": uid,
                "full_name": (meta.get("full_name") or meta.get("name") or "").strip(),
                "email": (au.get("email") or "").strip(),
            }
        )
    return out


def _sync_profiles_from_auth():
    """Auth'daki full_name -> profiles tablosu (service role gerekir)."""
    users = _fetch_auth_users()
    if not users:
        return 0
    synced = 0
    headers = _headers(service=True)
    headers["Prefer"] = "resolution=merge-duplicates"
    for au in users:
        uid = str(au.get("id", "")).strip()
        if not uid:
            continue
        meta = au.get("user_metadata") or {}
        row = {
            "id": uid,
            "full_name": (meta.get("full_name") or meta.get("name") or "").strip(),
        }
        contact = (au.get("email") or "").strip()
        if contact:
            row["username"] = contact
        r = _http.post(
            f"{SUPABASE_BASE}/profiles",
            headers=headers,
            json=row,
            timeout=12,
        )
        if r.status_code in (200, 201, 204):
            synced += 1
    if synced:
        print(f"profiles guncellendi: {synced} kullanici", flush=True)
    return synced


def _fetch_auth_users() -> list[dict]:
    """Tum kayitli hesaplar — SUPABASE_SERVICE_ROLE_KEY gerekir."""
    if not SUPABASE_SERVICE_KEY:
        return []
    r = _http.get(
        f"{SUPABASE_AUTH_URL}/admin/users",
        headers=_headers(service=True),
        params={"per_page": "200"},
        timeout=15,
    )
    if r.status_code != 200:
        print(f"Auth admin list: {r.status_code} {r.text[:200]}", flush=True)
        return []
    body = r.json()
    if isinstance(body, dict) and "users" in body:
        return body["users"]
    if isinstance(body, list):
        return body
    return []


def _display_name(
    user_id: str, profile: Optional[dict], auth_user: Optional[dict]
) -> str:
    if profile:
        name = (profile.get("full_name") or "").strip()
        if name:
            return name
        contact = _profile_contact(profile) if profile else ""
        if contact:
            return contact.split("@")[0]
    if auth_user:
        meta = auth_user.get("user_metadata") or {}
        name = (meta.get("full_name") or meta.get("name") or "").strip()
        if name:
            return name
        email = (auth_user.get("email") or "").strip()
        if email:
            return email.split("@")[0]
    if profile and _profile_contact(profile):
        return _profile_contact(profile).split("@")[0]
    return f"Kullanici ({_short_uid(user_id)})"


def _is_risky_sensor(sensor: Optional[dict]) -> bool:
    if not sensor:
        return False
    status = (sensor.get("status") or "SAFE").upper()
    if status in RISKY_STATUSES:
        return True
    if sensor.get("flame") in (True, "true", 1, "1"):
        return True
    try:
        return int(sensor.get("risk") or 0) >= 50
    except (TypeError, ValueError):
        return False


def _fetch_ppe_status() -> tuple[Optional[dict], bool]:
    """run_ppe_flask.py (port 5002) kamera analizi."""
    if not PPE_API_URL:
        return None, False
    try:
        r = _http.get(PPE_API_URL, timeout=4)
        if r.status_code == 200:
            body = r.json()
            if isinstance(body, dict):
                return body, True
    except Exception as e:
        print(f"PPE API ({PPE_API_URL}): {e}", flush=True)
    return None, False


def _ppe_violation_count(ppe: Optional[dict]) -> int:
    if not ppe or not ppe.get("person_detected"):
        return 0
    n = 0
    if ppe.get("hardhat_warning"):
        n += 1
    if ppe.get("safety_vest_warning"):
        n += 1
    if ppe.get("mask_warning"):
        n += 1
    return n


def _ppe_missing_labels(ppe: Optional[dict]) -> list[str]:
    if not ppe or not ppe.get("person_detected"):
        return []
    labels = []
    if ppe.get("hardhat_warning"):
        labels.append("Kask eksik")
    if ppe.get("safety_vest_warning"):
        labels.append("Yelek eksik")
    if ppe.get("mask_warning"):
        labels.append("Maske eksik")
    return labels


def _build_dashboard_stats(users_out: list[dict], ppe: Optional[dict], ppe_online: bool) -> dict:
    risky_users = [
        u for u in users_out if u.get("has_sensor_data") and _is_risky_sensor(u.get("sensor"))
    ]
    violations = _ppe_violation_count(ppe)
    missing = _ppe_missing_labels(ppe)

    ppe_summary = "Kamera kapalı — python run_ppe_flask.py çalıştırın"
    if ppe_online and ppe:
        if not ppe.get("person_detected"):
            ppe_summary = "Kamera açık — sahnede kişi yok"
        elif violations == 0:
            ppe_summary = "Kişi tespit edildi — tüm KKD tamam"
        else:
            ppe_summary = "KKD ihlali: " + ", ".join(missing)

    active_workers = sum(1 for u in users_out if u.get("has_sensor_data"))

    return {
        "active_workers": active_workers,
        "registered_users": len(users_out),
        "risky_count": len(risky_users),
        "ppe_violations": violations,
        "ppe_online": ppe_online,
        "ppe_person_detected": bool(ppe and ppe.get("person_detected")),
        "ppe_missing": missing,
        "ppe_summary": ppe_summary,
        "ppe": {
            "person_detected": bool(ppe and ppe.get("person_detected")),
            "hardhat_warning": bool(ppe and ppe.get("hardhat_warning")),
            "safety_vest_warning": bool(ppe and ppe.get("safety_vest_warning")),
            "mask_warning": bool(ppe and ppe.get("mask_warning")),
            "updated_at": (ppe or {}).get("updated_at"),
        },
        "risky_names": [u.get("display_name") or "?" for u in risky_users],
    }


def _sensor_histories_for_users(user_ids: list[str], per_user: int = HISTORY_PER_USER) -> dict[str, list]:
    """Son olcumler — grafik icin (kullanici basina kronolojik)."""
    if not user_ids:
        return {}
    want = set(user_ids)
    buckets: dict[str, list] = {uid: [] for uid in user_ids}
    r = _http.get(
        f"{SUPABASE_BASE}/sensor_data",
        headers=_headers(),
        params={
            "select": HISTORY_SELECT,
            "order": "created_at.desc",
            "limit": "1500",
        },
        timeout=25,
    )
    if r.status_code != 200:
        return buckets

    for row in r.json():
        uid = str(row.get("user_id", "")).strip()
        if uid not in want or len(buckets[uid]) >= per_user:
            continue
        buckets[uid].append(
            {
                "created_at": row.get("created_at"),
                "heart_rate": float(row.get("heart_rate") or 0),
                "body_temp": float(row.get("body_temp") or 0),
                "ambient_temp": float(row.get("ambient_temp") or 0),
                "humidity": float(row.get("humidity") or 0),
                "gas_percent": float(row.get("gas_percent") or 0),
                "gas_percent2": float(row.get("gas_percent2") or 0),
            }
        )

    for uid in buckets:
        buckets[uid].reverse()
    return buckets


def _latest_sensor_per_user(limit_rows: int = 800) -> dict[str, dict]:
    r = _http.get(
        f"{SUPABASE_BASE}/sensor_data",
        headers=_headers(),
        params={
            "select": SENSOR_SELECT,
            "order": "created_at.desc",
            "limit": str(limit_rows),
        },
        timeout=20,
    )
    if r.status_code != 200:
        raise RuntimeError(f"sensor_data okunamadi ({r.status_code}): {r.text[:300]}")

    latest: OrderedDict[str, dict] = OrderedDict()
    for row in r.json():
        uid = str(row.get("user_id", "")).strip()
        if not uid or uid in latest:
            continue
        latest[uid] = row
    return latest


def _build_users_payload():
    """Sadece public.profiles tablosundaki kayitlar (auth'taki tum hesaplar degil)."""
    if SUPABASE_SERVICE_KEY:
        _sync_profiles_from_auth()

    latest_sensors = _latest_sensor_per_user()
    registered = _fetch_all_profiles()

    setup_hint = None
    if not registered:
        setup_hint = (
            "Supabase profiles tablosu bos. SQL: supabase/fix_web_dashboard_profiles.sql"
        )

    users_out = []
    for reg in registered:
        uid = reg["id"]
        sensor = latest_sensors.get(uid)
        profile = {"full_name": reg.get("full_name"), "email": reg.get("email")}
        users_out.append(
            {
                "user_id": uid,
                "display_name": _display_name(uid, profile, None),
                "email": reg.get("email") or "",
                "has_sensor_data": sensor is not None,
                "sensor": sensor,
            }
        )

    users_out.sort(key=lambda u: (u.get("display_name") or "").lower())

    sensor_uids = [u["user_id"] for u in users_out if u.get("has_sensor_data")]
    histories = _sensor_histories_for_users(sensor_uids)
    for u in users_out:
        hist = histories.get(u["user_id"], [])
        if not hist and u.get("sensor"):
            s = u["sensor"]
            hist = [
                {
                    "created_at": s.get("created_at"),
                    "heart_rate": float(s.get("heart_rate") or 0),
                    "body_temp": float(s.get("body_temp") or 0),
                    "ambient_temp": float(s.get("ambient_temp") or 0),
                    "humidity": float(s.get("humidity") or 0),
                    "gas_percent": float(s.get("gas_percent") or s.get("gas_level") or 0),
                    "gas_percent2": float(s.get("gas_percent2") or s.get("gas_level2") or 0),
                }
            ]
        u["history"] = hist

    ppe_raw, ppe_online = _fetch_ppe_status()
    stats = _build_dashboard_stats(users_out, ppe_raw, ppe_online)

    return {
        "count": len(users_out),
        "users": users_out,
        "setup_hint": setup_hint,
        "stats": stats,
    }


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "service": "dashboard_api"})


@app.route("/api/dashboard/users")
def dashboard_users():
    try:
        return jsonify(_build_users_payload()), 200
    except Exception as e:
        print(f"dashboard_users hata: {e}", flush=True)
        return jsonify({"error": str(e)}), 500


@app.route("/api/ppe/stream")
def ppe_stream_proxy():
    """MJPEG — web panel canli kamera (run_ppe_flask video_feed)."""
    url = f"{_ppe_base_url()}/video_feed"
    try:
        upstream = _http.get(url, stream=True, timeout=(4, 120))
        if upstream.status_code != 200:
            return jsonify({"error": "Kamera yayini acik degil"}), 503

        def generate():
            try:
                for chunk in upstream.iter_content(chunk_size=8192):
                    if chunk:
                        yield chunk
            finally:
                upstream.close()

        ctype = upstream.headers.get(
            "Content-Type", "multipart/x-mixed-replace; boundary=frame"
        )
        return Response(generate(), mimetype=ctype)
    except Exception as e:
        print(f"PPE stream proxy: {e}", flush=True)
        return jsonify({"error": str(e)}), 503


@app.route("/api/ppe/frame")
def ppe_frame_proxy():
    """Tek JPEG kare — yedek onizleme."""
    url = f"{_ppe_base_url()}/api/frame"
    try:
        r = _http.get(url, timeout=5)
        if r.status_code == 200:
            return Response(r.content, mimetype="image/jpeg")
        return jsonify({"error": "Kare henuz yok"}), r.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 503


@app.route("/api/dashboard/users/<user_id>")
def dashboard_user_one(user_id):
    if not UUID_RE.match(user_id):
        return jsonify({"error": "Gecersiz user_id"}), 400
    try:
        payload = _build_users_payload()
        for u in payload["users"]:
            if u["user_id"] == user_id:
                return jsonify(u), 200
        return jsonify({"error": "Kullanici bulunamadi"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/")
def web_index():
    return send_from_directory(WEB_DIR, "index.html")


@app.route("/styles.css")
def web_css():
    return send_from_directory(WEB_DIR, "styles.css")


@app.route("/app.js")
def web_js():
    return send_from_directory(WEB_DIR, "app.js")


@app.route("/chart.umd.min.js")
def web_chart_js():
    return send_from_directory(WEB_DIR, "chart.umd.min.js")


if __name__ == "__main__":
    port = int(os.environ.get("DASHBOARD_PORT", "5003"))
    print("=" * 50, flush=True)
    print(f"  WEB:  http://127.0.0.1:{port}/", flush=True)
    print(f"  (ayni ag: http://192.168.43.218:{port}/ )", flush=True)
    print("  NOT: https degil, http kullanin", flush=True)
    print(f"  PPE:  {PPE_API_URL}", flush=True)
    print("=" * 50, flush=True)
    if not os.path.isfile(os.path.join(WEB_DIR, "index.html")):
        print(f"HATA: {WEB_DIR}/index.html yok!", flush=True)
    if SUPABASE_SERVICE_KEY:
        print("Isimler: auth -> profiles otomatik senkron", flush=True)
    else:
        print(
            "Isimler icin: .env dosyasina SUPABASE_SERVICE_ROLE_KEY ekleyin\n"
            "  veya Supabase SQL: supabase/profiles_dashboard.sql calistirin",
            flush=True,
        )
    try:
        app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
    except OSError as e:
        print(f"\nPort {port} kullanimda! Eski dashboard_api/debug oturumunu kapatin.", flush=True)
        print(f"Detay: {e}", flush=True)
