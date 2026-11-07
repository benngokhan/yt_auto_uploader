#!/usr/bin/env python3
"""api-kota.yml içinden çağrılır: panelden gelen anahtar kaydının GERÇEK sonucunu yazar."""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ad = os.environ.get("SECRET_ADI", "")
sonuc = os.environ.get("SECRET_SONUC", "0") == "1"
mesaj = os.environ.get("SECRET_MESAJ", "")

Path("api_secret_sonuc.json").write_text(json.dumps({
    "secret_adi": ad,
    "ok": sonuc,
    "mesaj": mesaj,
    "zaman": datetime.now(timezone.utc).isoformat(),
}, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"sonuc yazildi: {ad} ok={sonuc}")
