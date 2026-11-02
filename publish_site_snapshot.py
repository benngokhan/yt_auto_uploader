"""shorts_top.json dosyasını herkese açık site deposuna (GitHub Pages) yayınlar.

Özel depo (yt_auto_uploader) herkese açık olmadığı için ana sayfa telemetriyi
doğrudan okuyamaz. Bu betik, üretilen küçük anlık görüntüyü
`benngokhan/benngokhan.github.io` deposuna `data/shorts_top.json` olarak yazar.

Gereken: SITE_SYNC_TOKEN ortam değişkeni (public repo yazma yetkili token).
Token yoksa sessizce atlar (iş akışını kırmaz).
"""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SOURCE = BASE_DIR / "shorts_top.json"
TARGET_REPO = "benngokhan/benngokhan.github.io"
TARGET_PATH = "data/shorts_top.json"
TARGET_BRANCH = "main"


def _request(url: str, token: str, method: str = "GET", body: dict | None = None) -> dict | None:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "bilgidozu-site-sync",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else None
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def main() -> int:
    token = (os.environ.get("SITE_SYNC_TOKEN") or "").strip()
    if not token:
        print("[site] SITE_SYNC_TOKEN tanimli degil; yayin atlandi.")
        return 0
    if not SOURCE.exists():
        print("[site] shorts_top.json yok; once export_site_snapshot.py calistirilmali.")
        return 1

    payload = SOURCE.read_bytes()
    local_text = payload.decode("utf-8")
    json.loads(local_text)  # geçerli JSON kontrolü

    api = f"https://api.github.com/repos/{TARGET_REPO}/contents/{TARGET_PATH}"
    current = _request(f"{api}?ref={TARGET_BRANCH}", token)
    sha = None
    if current:
        sha = current.get("sha")
        remote_text = base64.b64decode(current.get("content", "")).decode("utf-8")
        if remote_text.strip() == local_text.strip():
            print("[site] Icerik ayni; commit atildi (boss ilerleme).")
            return 0

    body = {
        "message": "chore(data): shorts_top.json panel telemetrisinden guncellendi [skip ci]",
        "content": base64.b64encode(payload).decode("ascii"),
        "branch": TARGET_BRANCH,
    }
    if sha:
        body["sha"] = sha
    result = _request(api, token, method="PUT", body=body)
    commit = ((result or {}).get("commit") or {}).get("sha", "")[:8]
    print(f"[site] shorts_top.json yayinlandi (commit={commit or 'ok'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
