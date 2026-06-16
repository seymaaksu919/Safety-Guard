"""
Bir kez calistirin — auth'daki tum isimleri profiles tablosuna yazar.
Sonra web dashboard'da isim listesi gorunur.

  python sync_user_names.py

.env dosyasinda SUPABASE_SERVICE_ROLE_KEY olmali.
"""

import os
import sys

import requests

# dashboard_api ile ayni ayarlar
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dashboard_api import (  # noqa: E402
    SUPABASE_BASE,
    _fetch_auth_users,
    _headers,
    _load_env_file,
)

_load_env_file()
SERVICE = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()


def main():
    if not SERVICE:
        print("HATA: .env icinde SUPABASE_SERVICE_ROLE_KEY yok.")
        print("Supabase -> Settings -> API -> service_role")
        sys.exit(1)

    users = _fetch_auth_users()
    if not users:
        print("Auth kullanici listesi alinamadi.")
        sys.exit(1)

    headers = _headers(service=True)
    headers["Prefer"] = "resolution=merge-duplicates"
    ok = 0
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
        r = requests.post(
            f"{SUPABASE_BASE}/profiles",
            headers=headers,
            json=row,
            timeout=12,
        )
        if r.status_code in (200, 201, 204):
            ok += 1
            print(f"  OK: {row['full_name'] or row['email'] or uid}")
        else:
            print(f"  HATA {uid}: {r.status_code} {r.text[:120]}")

    print(f"\nToplam {ok}/{len(users)} kullanici profiles'a yazildi.")
    print("Simdi: python dashboard_api.py  ->  http://127.0.0.1:5003/")


if __name__ == "__main__":
    main()
