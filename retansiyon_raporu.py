#!/usr/bin/env python3
"""
Retansiyon Raporu — YouTube Analytics API (youtubeanalytics.readonly).

Her gün 11:30 TR (08:30 UTC) cron:
  1. Refresh token -> access token
  2. Son 30 gün, dimensions=video: averageViewDuration + percentViewed + retained
  3. bilgidozu_yukleme_tablosu.xlsx'e iki yeni sütun yazar (yoksa ekler):
       - "Ort. İzlenme (sn)"   -> kanca + içerik kalitesi ölçütü (saniye)
       - "% İzlenen"            -> 3. saniye kancasının proxy'si (yüzde)
  4. Özet: stats_retansiyon.json + log'a top 3 / bottom 3.

YouTube API kotası harcamaz (Analytics ayrı kota havuzu; sıfır-quota kuralı korunur).
Env: YT_CLIENT_ID, YT_CLIENT_SECRET, YT_ANALYTICS_REFRESH_TOKEN
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import openpyxl

TABLO = "bilgidozu_yukleme_tablosu.xlsx"
OUT_JSON = "stats_retansiyon.json"
COL_VIEW_SN = "Ort. İzlenme (sn)"
COL_PCT = "% İzlenen"
GUN = 30  # ortalama penceresi

TOKEN_URL = "https://oauth2.googleapis.com/token"
API_BASE = "https://analytics.googleapis.com/v2/management"
REDIRECT_URI = "https://qkn0.up.railway.app/analytics/oauth/callback"


def http_json(url, headers=None, data=None, method=None):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode("utf-8"))


def access_token_cek():
    d = urllib.parse.urlencode(
        {
            "client_id": os.environ["YT_CLIENT_ID"],
            "client_secret": os.environ["YT_CLIENT_SECRET"],
            "refresh_token": os.environ["YT_ANALYTICS_REFRESH_TOKEN"],
            "grant_type": "refresh_token",
        }
    ).encode()
    r = http_json(
        TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=d,
        method="POST",
    )
    if "access_token" not in r:
        raise RuntimeError(f"Token yenilemede hata: {r}")
    return r["access_token"]


def retention_cek(token, bas, bit):
    """Son 30 günün video-bazlı ortalama metrikleri. {video_id: {avd, pct, ret}}"""
    q = urllib.parse.urlencode(
        {
            "entityType": "video",
            "startDate": bas.strftime("%Y%m%d"),
            "endDate": bit.strftime("%Y%m%d"),
            "metrics": "averageViewDuration,percentViewed,retained",
            "dimensions": "video",
            "maxResults": 5000,
        }
    )
    r = http_json(
        f"{API_BASE}/retention?{q}",
        headers={"Authorization": f"Bearer {token}"},
    )
    out = {}
    for row in r.get("data", []):
        dims = row.get("dimensions", {}) or {}
        vid = dims.get("video") or dims.get("externalId") or ""
        m = row.get("metrics", {}) or {}
        if not vid:
            continue
        try:
            avd = float(m.get("averageViewDuration") or 0.0)
            pct = float(m.get("percentViewed") or 0.0) * 100.0
            ret = float(m.get("retained") or 0.0) * 100.0
        except (TypeError, ValueError):
            continue
        if vid in out:  # aynı video birden fazla satırdaysa ortala
            o = out[vid]
            n = o["n"]
            o["avd"] = (o["avd"] * n + avd) / (n + 1)
            o["pct"] = (o["pct"] * n + pct) / (n + 1)
            o["ret"] = (o["ret"] * n + ret) / (n + 1)
            o["n"] = n + 1
        else:
            out[vid] = {"avd": avd, "pct": pct, "ret": ret, "n": 1}
    return out


def video_id_cek(link):
    if not isinstance(link, str):
        return None
    s = link.strip()
    for pref in ("https://youtu.be/", "http://youtu.be/"):
        if pref in s:
            return s.split(pref, 1)[1].split("/")[0].split("?")[0] or None
    if "v=" in s:
        v = s.split("v=", 1)[1].split("&")[0].split("/")[0]
        return v or None
    return None


def main():
    token = access_token_cek()
    bugun = datetime.now(timezone.utc).date()
    bit = bugun - timedelta(days=1)  # API'de dün'e kadar verisi stabil
    bas = bit - timedelta(days=GUN - 1)
    print(f"[ret] Pencere: {bas} -> {bit}")

    data = retention_cek(token, bas, bit)
    print(f"[ret] {len(data)} videonun metrikleri geldi")

    wb = openpyxl.load_workbook(TABLO)
    ws = wb.active
    headers = [c.value for c in ws[1]]

    if "YouTube Link" not in headers:
        print("[ret] HATA: 'YouTube Link' sütunu yok — tablo formatı değişti mi?", file=sys.stderr)
        sys.exit(1)
    link_col = headers.index("YouTube Link") + 1

    # Yeni sütunlar: varsa indexini kullan, yoksa sona ekle
    def sütun(index_hedef):
        if index_hedef in headers:
            return headers.index(index_hedef) + 1
        yeni = len(headers) + 1
        ws.cell(row=1, column=yeni, value=index_hedef)
        headers.append(index_hedef)
        return yeni

    col_sn = sütun(COL_VIEW_SN)
    col_pct = sütun(COL_PCT)

    güncellenen = 0
    satirlar = []
    for r in range(2, ws.max_row + 1):
        link = ws.cell(row=r, column=link_col).value
        vid = video_id_cek(link)
        if not vid or vid not in data:
            continue
        d = data[vid]
        ws.cell(row=r, column=col_sn, value=round(d["avd"], 1))
        ws.cell(row=r, column=col_pct, value=round(d["pct"]))
        başlık = ws.cell(row=r, column=1).value
        satirlar.append({"satır": r, "başlık": başlık, "vid": vid,
                         "avd": round(d["avd"], 1), "pct": round(d["pct"]),
                         "ret": round(d["ret"])})
        güncellenen += 1

    wb.save(TABLO)

    if satirlar:
        sıralı = sorted(satirlar, key=lambda x: x["pct"], reverse=True)
        ort = sorted(x["pct"] for x in satirlar)
        med = ort[len(ort) // 2]
        print(f"[ret] {güncellenen} satır güncellendi · kanal medyanı % izlenen: {med}%")
        print("[ret] TOP 3  % izlenen:", ", ".join(f"{x['başlık'][:40]}={x['pct']}%" for x in sıralı[:3]))
        print("[ret] BOT 3  % izlenen:", ", ".join(f"{x['başlık'][:40]}={x['pct']}%" for x in sıralı[-3:]))
    else:
        print("[ret] UYARI: tablodaki hiçbir linkin Analytics verisi yok")

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(
            {"pencere": [str(bas), str(bit)], "video_sayisi": len(satirlar),
             "satirlar": satirlar},
            f, ensure_ascii=False, indent=2,
        )
    print(f"[ret] {OUT_JSON} yazıldı")


if __name__ == "__main__":
    main()
