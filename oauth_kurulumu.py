#!/usr/bin/env python3
"""
OAuth Kurulumu (tek seferlik):
  1. Google consent'ten alinan ?code= -> access + REFRESH token takasi
  2. Analytics API'ye test istegi (token'un calistigini kanitla)
  3. Refresh token + client kimlikleri repo secret'lari olarak sakla
     (AES-256-GCM, GitHub Actions secret sifreleme)
Env: KOD, YT_CLIENT_ID, YT_CLIENT_SECRET, GITHUB_TOKEN, GH_REPO
"""
import base64
import json
import os
import urllib.parse
import urllib.request

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

REPO = os.environ["GH_REPO"]
GH_TOKEN = os.environ["GITHUB_TOKEN"]
REDIRECT_URI = "https://qkn0.up.railway.app/analytics/oauth/callback"
API_BASE = "https://analytics.googleapis.com/v2/management"


def gh_req(method, path, body=None):
    h = {"Authorization": f"Bearer {GH_TOKEN}", "Accept": "application/vnd.github+json"}
    if body is not None:
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers=h,
        method=method,
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    d = urllib.parse.urlencode(
        {
            "code": os.environ["KOD"],
            "client_id": os.environ["YT_CLIENT_ID"],
            "client_secret": os.environ["YT_CLIENT_SECRET"],
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code",
        }
    ).encode()
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=d,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        t = json.loads(r.read().decode("utf-8"))
    if "refresh_token" not in t:
        print("[auth] YENI refresh_token alinamadi (muhtemelen once yetkilendirilmis) — eski token kalinir")
    else:
        print(f"[auth] Yeni refresh_token alindi ({t['refresh_token'][:12]}...)")

    # 1) API testi
    q = urllib.parse.urlencode(
        {"entityType": "channel", "startDate": "20261021", "endDate": "20261028",
         "metrics": "averageViewDuration"}
    )
    req = urllib.request.Request(
        f"{API_BASE}/retention?{q}",
        headers={"Authorization": f"Bearer {t['access_token']}"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        r.read()
    print("[auth] Analytics API cevabi geldi — yetki ONAYLANDI")

    # 2) Secret'lari kaydet
    public = gh_req("GET", f"/repos/{REPO}/actions/secrets/public-key")
    key = serialization.load_pem_public_key(base64.b64decode(public["key"]))
    secrets = {
        "YT_CLIENT_ID": os.environ["YT_CLIENT_ID"],
        "YT_CLIENT_SECRET": os.environ["YT_CLIENT_SECRET"],
    }
    if "refresh_token" in t:
        secrets["YT_ANALYTICS_REFRESH_TOKEN"] = t["refresh_token"]
    for isim, deger in secrets.items():
        enc = sifrele(key, deger.encode("utf-8"))
        gh_req("PUT", f"/repos/{REPO}/actions/secrets/{isim}",
               {"key_id": public["key_id"], "encrypted_value": enc})
        print(f"[auth] Secret kaydedildi: {isim}")
    print("[auth] TAMAM — retansiyon raporu her gün 11:30 TR otomatik calisacak")


def sifrele(pub, veriler):
    anahtar = pub.encrypt(
        AESGCM.generate_key(bit_length=256),
        padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA1()), algorithm=hashes.SHA1(), label=None),
    )
    return base64.b64encode(AESGCM(anahtar).encrypt(anahtar + os.urandom(12), veriler, None)).decode()


if __name__ == "__main__":
    main()
