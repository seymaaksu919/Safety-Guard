"""
PPE siber guvenlik testi (Flask acikken).

  python test_security.py 2
  python test_security.py --senaryo 5
  python test_security.py --hepsi

Flask: python run_ppe_flask.py
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import requests

try:
    import websocket
except ImportError:
    websocket = None

_MIN_JPEG = bytes([0xFF, 0xD8, 0xFF, 0xD9])
_DIR = Path(__file__).resolve().parent


@dataclass
class Senaryo:
    no: int
    ad: str
    kanal: str
    gonderilen: str
    beklenen: str


@dataclass
class Config:
    base: str
    dogru_key: str
    yanlis_key: str
    max_skew: int

    @property
    def post_url(self) -> str:
        return f"{self.base}/camera-data"

    @property
    def ws_base(self) -> str:
        return self.base.replace("http://", "ws://")


def _varsayilan_key() -> str:
    p = _DIR / "run_ppe_flask.py"
    try:
        t = p.read_text(encoding="utf-8")
        m = re.search(
            r'GIZLI_KEY\s*=\s*os\.environ\.get\([^,]+,\s*["\']([^"\']+)["\']',
            t,
        )
        if m:
            return m.group(1)
    except OSError:
        pass
    return "fabrika_ortak_gizli_key_123"


def _flask_ayakta(cfg: Config) -> bool:
    try:
        return requests.get(f"{cfg.base}/api/status", timeout=4).status_code == 200
    except requests.RequestException:
        return False


def _post(cfg: Config, key: str, ts: int) -> tuple[int, str]:
    try:
        r = requests.post(
            cfg.post_url,
            headers={
                "X-API-Key": key,
                "X-Timestamp": str(ts),
                "Content-Type": "image/jpeg",
            },
            data=_MIN_JPEG,
            timeout=10,
        )
        return r.status_code, (r.text or "")[:120]
    except requests.RequestException as e:
        return 0, str(e)


def _ws(cfg: Config, key: str, ts: int) -> str:
    if not websocket:
        raise RuntimeError("pip install websocket-client")
    url = f"{cfg.ws_base}/ws/camera?api_key={key}&ts={ts}&device_id=test"
    ws = websocket.create_connection(url, timeout=8)
    try:
        return (ws.recv() or "")[:120]
    finally:
        ws.close()


def _anahtar(verilen: str | None) -> str:
    if verilen:
        return verilen
    return os.environ.get("PPE_API_KEY") or _varsayilan_key()


def _senaryolar() -> list[Senaryo]:
    return [
        Senaryo(1, "Yanlis sifre", "POST", "Yanlis API key", "REDDET (401)"),
        Senaryo(2, "Eski saat", "POST", "Dogru key, cok eski zaman", "REDDET (403)"),
        Senaryo(3, "Dogru istek", "POST", "Dogru key + simdi", "KABUL"),
        Senaryo(4, "Yanlis sifre", "WS", "Yanlis API key", "REDDET"),
        Senaryo(5, "Eski saat", "WS", "Dogru key, cok eski zaman", "REDDET (zaman)"),
        Senaryo(6, "Dogru baglanti", "WS", "Dogru key + simdi", "KABUL (AUTH_OK)"),
    ]


def _menu() -> None:
    print("Senaryo sec (1-6):")
    for s in _senaryolar():
        print(f"  {s.no}  {s.kanal:<4}  {s.ad}")
    print("\nOrnek: python test_security.py 2")


def _kos(cfg: Config, s: Senaryo) -> dict:
    simdi = int(time.time())
    eski = simdi - cfg.max_skew - 30

    try:
        if s.kanal == "POST":
            if s.no == 1:
                kod, govde = _post(cfg, cfg.yanlis_key, simdi)
                gecti = kod == 401
            elif s.no == 2:
                kod, govde = _post(cfg, cfg.dogru_key, eski)
                gecti = kod == 403
            else:
                kod, govde = _post(cfg, cfg.dogru_key, simdi)
                gecti = kod in (200, 400) and "REJECTED" not in govde and "ATTACK" not in govde
            oldu = f"HTTP {kod} | {govde}"
        elif s.no == 4:
            msg = _ws(cfg, cfg.yanlis_key, simdi)
            oldu = msg
            gecti = "REJECTED" in msg
        elif s.no == 5:
            msg = _ws(cfg, cfg.dogru_key, eski)
            oldu = msg
            gecti = "REJECTED" in msg and ("Zaman" in msg or "asimi" in msg)
        else:
            msg = _ws(cfg, cfg.dogru_key, simdi)
            oldu = msg
            gecti = "AUTH_OK" in msg
    except Exception as e:
        oldu = str(e)
        gecti = False

    return {
        "no": s.no,
        "ad": s.ad,
        "kanal": s.kanal,
        "gonderilen": s.gonderilen,
        "beklenen": s.beklenen,
        "oldu": oldu,
        "durum": "SIBER OK" if gecti else "SIBER HATA",
        "gecti": gecti,
    }


def _yaz(r: dict) -> None:
    print(f"\nSENARYO {r['no']}/6 — {r['ad']} ({r['kanal']})")
    print(f"  Gonderilen : {r['gonderilen']}")
    print(f"  Beklenen   : {r['beklenen']}")
    print(f"  Sunucu     : {r['oldu']}")
    print(f"  Sonuc      : {r['durum']}\n")


def main() -> int:
    p = argparse.ArgumentParser(description="PPE siber test")
    p.add_argument("senaryo", nargs="?", type=int, choices=range(1, 7))
    p.add_argument("--senaryo", type=int, dest="senaryo_flag", choices=range(1, 7))
    p.add_argument("--port", type=int, default=int(os.environ.get("PPE_PORT", "5002")))
    p.add_argument("--key", help="Flask API key")
    p.add_argument("--hepsi", action="store_true")
    args = p.parse_args()

    no = args.senaryo_flag or args.senaryo
    if not args.hepsi and no is None:
        _menu()
        return 1

    key = _anahtar(args.key)
    cfg = Config(
        base=f"http://127.0.0.1:{args.port}",
        dogru_key=key,
        yanlis_key=f"{key}_YANLIS",
        max_skew=int(os.environ.get("PPE_TIMESTAMP_MAX_SKEW", "5")),
    )

    print("=" * 50)
    print(f"ZAMAN: {time.strftime('%H:%M:%S')}  |  Key: {cfg.dogru_key}")
    print("=" * 50)

    if not _flask_ayakta(cfg):
        print("Flask kapali → python run_ppe_flask.py")
        return 1

    if args.hepsi:
        sonuclar = [_kos(cfg, s) for s in _senaryolar()]
        for r in sonuclar:
            _yaz(r)
        g = sum(1 for r in sonuclar if r["gecti"])
        print(f"Toplam: {g}/6")
        return 0 if g == 6 else 1

    s = _senaryolar()[no - 1]
    r = _kos(cfg, s)
    _yaz(r)
    return 0 if r["gecti"] else 1


if __name__ == "__main__":
    sys.exit(main())
