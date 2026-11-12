#!/usr/bin/env python3
import datetime
import json
import os
import urllib.error
import urllib.request

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def call(name, req):
    out = {"durum": "hata", "http": 0, "limit": {}, "mesaj": ""}
    req.add_unredirected_header("User-Agent", UA)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            r.read()
            out["durum"] = "aktif"
            out["http"] = r.status
            h = {k.lower(): v for k, v in r.headers.items()}
    except urllib.error.HTTPError as e:
        out["http"] = e.code
        h = {k.lower(): v for k, v in e.headers.items()}
        raw = e.read().decode(errors="replace")
        try:
            j = json.loads(raw)
            err = j.get("error")
            out["mesaj"] = (err.get("message", raw) if isinstance(err, dict) else str(err or raw))[:240]
        except Exception:
            out["mesaj"] = raw[:240]
        out["durum"] = "kota" if e.code == 429 else "hata"
    except Exception as e:
        h = {}
        out["mesaj"] = str(e)[:240]
    for k, v in h.items():
        if k.startswith("x-ratelimit-"):
            out["limit"][k.replace("x-ratelimit-", "")] = v
    # Pexels 'x-ratelimit-remaining' / 'x-ratelimit-limit' başlıklarını 'remaining-requests'/'limit-requests' ile de eşle
    if "remaining" in out["limit"] and "remaining-requests" not in out["limit"]:
        out["limit"]["remaining-requests"] = out["limit"]["remaining"]
    if "limit" in out["limit"] and "limit-requests" not in out["limit"]:
        out["limit"]["limit-requests"] = out["limit"]["limit"]
    return out


def main():
    gk = os.getenv("GEMINI_API_KEY", "").strip()
    qk = os.getenv("GROQ_API_KEY", "").strip()
    pk = (os.getenv("PEXELS_API_KEY") or os.getenv("PEXELS_KEY") or os.getenv("PEXELS_API") or "").strip()

    gem = (
        call("Gemini", urllib.request.Request("https://generativelanguage.googleapis.com/v1beta/models?key=" + gk))
        if gk
        else {"durum": "anahtar_yok", "http": 0, "limit": {}, "mesaj": ""}
    )
    body = {"model": "llama-3.3-70b-versatile", "messages": [{"role": "user", "content": "Sadece OK yaz."}], "max_tokens": 1}
    groq = (
        call(
            "Groq",
            urllib.request.Request(
                "https://api.groq.com/openai/v1/chat/completions",
                data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json", "Authorization": "Bearer " + qk},
            ),
        )
        if qk
        else {"durum": "anahtar_yok", "http": 0, "limit": {}, "mesaj": ""}
    )
    pexels = (
        call(
            "Pexels",
            urllib.request.Request(
                "https://api.pexels.com/v1/curated?per_page=1",
                headers={"Authorization": pk, "Accept": "application/json"},
            ),
        )
        if pk
        else {"durum": "anahtar_yok", "http": 0, "limit": {}, "mesaj": "PEXELS_API_KEY tanımlı değil"}
    )

    with open("api_durum.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "guncellendi": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "not": "Sağlayıcı yalnız sunduğu limit başlıklarını gösterir; Pexels gerçek kalan aylık isteği döndürür.",
                "gemini": gem,
                "groq": groq,
                "pexels": pexels,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )


if __name__ == "__main__":
    main()
