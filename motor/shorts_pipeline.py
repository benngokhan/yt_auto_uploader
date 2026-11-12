#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MİRA × BİLGİ DOZU RENDER MOTORU v2.0 (Onaylı Master Şablon v2)

Bu motor kanaldaki onaylı v2 Shorts şablonunu PİKSEL PİKSEL ve SES MİMARİSİYLE
birebir uygular:
  - 1080x1920 @ 30fps dikey tam ekran (MIRA_MOTOR_W/H/FPS ile ölçeklenebilir)
  - Üst neon-sarı ilerleme çubuğu (x=79..1043, y=48..56) + 3D kabartmalı
    "BİLGİ DOZU" rozeti (x=77..291, y=80..139, #E3F424)
  - Her sahnede konuya göre değişen <=20 karakter 2 satır TAM BÜYÜK HARF başlık
    (1. satır #FFFFFF, 2. satır #E3F424) + solunda anlam eşleşmeli sarı vektör
    ikon (?, ▼, ⚡, ▲, !, ✔) (y=287..430)
  - Tek kelime aktif sarı (#E3F424) karaoke altyazı: ekrana giren tüm kelimeler
    %100 net beyaz (#FFFFFF), SADECE o an okunan tek kelime #E3F424 (y=1131..1270)
  - Kapanış sahnesinde "takip et!" altında (y=1318..1382) 3D kabartmalı sarı
    [TAKİP ET] butonu + yaylı pop-in + tıklama basımı + halka dalgası + pop/click SFX
  - Alt kaynak + temsilî görsel notu + ortalı BİLGİ DOZU imzası (y=1751..1883)
  - Broadcast Ses Mimarisi:
      * 0.00 - 1.45 sn tam ses Bilgi Dozu jenerik intro (~ -14.8 dBFS)
      * Cümle aralarında ~0.62 sn doğal nefes esleri (müzik hafifçe yükselir)
      * Konuşma sırasında 50ms look-ahead, -15.6 dB auto-ducking + 850 Hz LPF
      * Kapanışta +1.45 sn tam ses jenerik outro + sabit lineer -14.2 LUFS master
  - Otomatik Shorts kapak görseli üretimi (<video_id>/kapak.jpg, 1080x1920)

Kullanım (Geriye %100 Uyumlu CLI):
  python3 shorts_pipeline.py <plates|timing|music|render|cover|all> <video_id> [config_path]
"""

import contextlib
import difflib
import gc
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont
import endcard_v2

HERE = os.path.dirname(os.path.abspath(__file__))


def _resolve_ffmpeg() -> str:
    envn = os.environ.get("MIRA_MOTOR_FFMPEG")
    if envn and os.path.exists(envn):
        return envn
    tf = os.path.join(tempfile.gettempdir(), "mira_motor_ffmpeg_path.txt")
    if os.path.exists(tf):
        try:
            cand = open(tf, encoding="utf-8").read().strip()
            if cand and os.path.exists(cand):
                return cand
        except Exception:
            pass
    p = os.path.join(HERE, "ffmpeg_path.txt")
    if os.path.exists(p):
        try:
            cand = open(p, encoding="utf-8").read().strip()
            if cand and os.path.exists(cand):
                return cand
        except Exception:
            pass
    which_ff = shutil.which("ffmpeg")
    if which_ff:
        return which_ff
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


FF = _resolve_ffmpeg()

# Çözünürlük & FPS (varsayılan 1080x1920 @ 30fps; MIRA_MOTOR_* ile override edilebilir)
W = int(os.environ.get("MIRA_MOTOR_W", "1080"))
H = int(os.environ.get("MIRA_MOTOR_H", "1920"))
FPS = int(os.environ.get("MIRA_MOTOR_FPS", "30"))
SR = 44100
S_SCALE = W / 1080.0


def S_(px: float) -> int:
    return max(1, int(round(px * S_SCALE)))


# Onaylı v2 Renk Paleti
BRAND_YEL = (227, 244, 36, 255)       # #E3F424 ana vurgu & aktif kelime & rozet
PROG_YEL = (217, 243, 38, 255)        # #D9F326 üst ilerleme çubuğu
BADGE_BEVEL = (154, 169, 13, 255)     # #9AA90D 3D alt kabartma gölgesi
DARK_TEXT = (15, 18, 21, 255)         # #0F1215 rozet & buton koyu metin
PURE_WHITE = (255, 255, 255, 255)     # #FFFFFF 1. satır başlık & pasif altyazı

# Ses & Zamanlama Sabitleri (Onaylı v2.1 Master + 3D Kapanış Kartı)
DEFAULT_INTRO_LEAD = 1.45
DEFAULT_SENT_PAUSE = 0.62
DEFAULT_OUTRO_HOLD = endcard_v2.OUTRO_HOLD_SEC  # 2.35 sn canlı 3D Kapanış Kartı tutuşu
DUCK_FLOOR = 0.165                              # -15.65 dB konuşma altı müzik seviyesi
TARGET_LUFS = -14.2


# ---------------------------------------------------------------- Türkçe & Font Yardımcıları
def N_(s: str) -> str:
    return unicodedata.normalize("NFC", str(s or ""))


def tr_upper(s: str) -> str:
    return N_(s).replace("i", "İ").replace("ı", "I").upper()


def tr_lower(s: str) -> str:
    return N_(s).replace("İ", "i").replace("I", "ı").lower()


def norm_word(w: str) -> str:
    s = tr_lower(w)
    s = s.replace("â", "a").replace("î", "i").replace("û", "u")
    return re.sub(r"[^\wçğıöşü0-9]", "", s)


FONT_SEARCH_DIRS = [
    os.path.join(HERE, "assets"),
    os.path.join(HERE, "fonts", "poppins"),
    os.path.join(HERE, "sablon_v165", "shorts", "fonts"),
    os.path.join(HERE, "fonts", "raw"),
]

FONT_FALLBACKS = {
    "Poppins-Bold.ttf": ["Poppins-Bold.ttf", "archivo.ttf", "ArchivoBlack-Regular.ttf"],
    "Poppins-SemiBold.ttf": ["Poppins-SemiBold.ttf", "Poppins-Bold.ttf", "inter.ttf"],
    "Poppins-Medium.ttf": ["Poppins-Medium.ttf", "Poppins-Regular.ttf", "inter.ttf"],
    "Poppins-Regular.ttf": ["Poppins-Regular.ttf", "inter.ttf"],
    "Anton-Regular.ttf": ["Anton-Regular.ttf", "anton.ttf", "ArchivoBlack-Regular.ttf", "archivo.ttf"],
}

_FONT_CACHE = {}


def load_font(name: str, size: int) -> ImageFont.FreeTypeFont:
    size = max(8, int(size))
    key = (name, size)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    candidates = FONT_FALLBACKS.get(name, [name, "Poppins-Bold.ttf", "archivo.ttf", "inter.ttf"])
    chosen = None
    for cand in candidates:
        for d in FONT_SEARCH_DIRS:
            p = os.path.join(d, cand)
            if os.path.exists(p):
                chosen = p
                break
        if chosen:
            break
    if not chosen:
        raise FileNotFoundError(f"Font bulunamadı: {name} ({FONT_SEARCH_DIRS})")
    try:
        fnt = ImageFont.truetype(chosen, size=size, layout_engine=ImageFont.Layout.BASIC)
    except Exception:
        fnt = ImageFont.truetype(chosen, size=size)
    _FONT_CACHE[key] = fnt
    return fnt


def wlen(draw: ImageDraw.ImageDraw, txt: str, font: ImageFont.FreeTypeFont) -> float:
    return draw.textlength(N_(txt), font=font)


def clamp01(v: float) -> float:
    return min(max(float(v), 0.0), 1.0)


def ease_out(t: float) -> float:
    return 1.0 - (1.0 - clamp01(t)) ** 3


def ease_io(t: float) -> float:
    x = clamp01(t)
    return x * x * (3.0 - 2.0 * x)


# ---------------------------------------------------------------- Konfigürasyon & Klasör Çözücü
def _resolve_context(vdir_arg: str, explicit_cfg_path: str = None):
    """Hem `shorts/s81_mira` (cwd=HERE) hem `s12_ornek` (cwd=shorts_dir, mira_adapter)
    çağrılarını otomatik ve hatasız çözümler."""
    candidates_dir = [
        os.path.abspath(vdir_arg),
        os.path.join(HERE, vdir_arg),
        os.path.join(HERE, "shorts", vdir_arg),
    ]
    work_dir = None
    for c in candidates_dir:
        if os.path.isdir(c):
            work_dir = c
            break
    if work_dir is None:
        work_dir = os.path.join(HERE, vdir_arg)
        os.makedirs(work_dir, exist_ok=True)

    cfg_candidates = []
    if explicit_cfg_path:
        cfg_candidates.append(explicit_cfg_path)
    if os.environ.get("MIRA_SHORTS_CONFIG"):
        cfg_candidates.append(os.environ["MIRA_SHORTS_CONFIG"])
    cfg_candidates.extend([
        os.path.join(os.path.dirname(work_dir), "shorts_config.json"),
        os.path.join(os.getcwd(), "shorts_config.json"),
        os.path.join(HERE, "shorts", "shorts_config.json"),
    ])

    conf_all = {}
    cfg_path_used = None
    for cp in cfg_candidates:
        if cp and os.path.exists(cp):
            conf_all = json.load(open(cp, encoding="utf-8"))
            cfg_path_used = cp
            break

    base = os.path.basename(work_dir.rstrip("/"))
    key_tries = [vdir_arg, base, f"shorts/{base}"]
    cfg = None
    for k in key_tries:
        if k in conf_all:
            cfg = conf_all[k]
            break
    if cfg is None:
        local_cfg = os.path.join(work_dir, "config.json")
        if os.path.exists(local_cfg):
            cfg = json.load(open(local_cfg, encoding="utf-8"))
        else:
            raise KeyError(f"'{vdir_arg}' için shorts_config.json kaydı bulunamadı ({cfg_path_used})")
    return work_dir, cfg, cfg_path_used


# ---------------------------------------------------------------- Başlık & Semantik İkon Üretici
STOPWORDS_TR = {
    "bir", "bu", "şu", "o", "ve", "ile", "için", "gibi", "kadar", "daha",
    "çok", "en", "her", "hiç", "ama", "fakat", "ancak", "yani", "işte",
    "aslında", "tam", "ise", "de", "da", "ki", "mi", "mı", "mu", "mü",
    "olarak", "olan", "olur", "olduğu", "sonra", "önce", "üzere", "göre",
    "nedeniyle", "sayesinde", "tarafından", "böylece", "üzerinde", "altında",
    "içinde", "arasında", "doğru", "karşı", "bile", "sadece", "yalnızca",
    "peki", "acaba", "neden", "nasıl", "ne",
}


def _flatten_title_lines(raw_title) -> list:
    """Eski Mira formatlarındaki iç içe listeleri temiz metin satırlarına çevirir."""
    if not raw_title:
        return []
    lines = []
    for item in raw_title:
        if isinstance(item, str):
            s = item.strip()
        elif isinstance(item, (list, tuple)):
            parts = []
            for sub in item:
                if isinstance(sub, str):
                    if sub not in ("g", "w", "y", ""):
                        parts.append(sub)
                elif isinstance(sub, (list, tuple)) and len(sub) >= 1:
                    if isinstance(sub[0], str):
                        parts.append(sub[0])
            s = " ".join(p.strip() for p in parts if p.strip())
        else:
            s = str(item).strip()
        if s:
            lines.append(tr_upper(s))
    return lines


def _wrap_two_lines_20(text_upper: str, max_chars: int = 20) -> tuple:
    """Metni kelime ortasından bölmeden <=20 karakterlik 2 satıra sığdırır."""
    words = [w for w in tr_upper(text_upper).split() if w]
    if not words:
        return ("BİLGİ DOZU", "BİLİMSEL GERÇEK")
    if len(words) == 1:
        w0 = words[0][:max_chars]
        return (w0, "GERÇEĞİ")

    # En dengeli 2 satır bölünmesini bul
    best_pair = None
    best_score = 1e9
    for split_idx in range(1, len(words)):
        l1 = " ".join(words[:split_idx])
        l2 = " ".join(words[split_idx:])
        over1 = max(0, len(l1) - max_chars) * 12
        over2 = max(0, len(l2) - max_chars) * 12
        diff = abs(len(l1) - len(l2))
        score = over1 + over2 + diff
        if score < best_score:
            best_score = score
            best_pair = (l1, l2)

    l1, l2 = best_pair
    # Hâlâ >max_chars ise fazla kelimeleri kırp
    while len(l1) > max_chars and " " in l1:
        l1 = l1.rsplit(" ", 1)[0]
    while len(l2) > max_chars and " " in l2:
        l2 = l2.rsplit(" ", 1)[0]
    return (l1[:max_chars], l2[:max_chars])


def _classify_semantic_icon(sent: str, idx: int, total_scenes: int) -> str:
    """Cümlenin anlamına göre onaylı 6 semantik sarı ikondan (?, ▼, ⚡, ▲, !, ✔) birini seçer."""
    low = tr_lower(sent)
    if "?" in sent or idx == total_scenes - 1 or any(q in low for q in ("hiç merak", "bilir misin", "fark ettin mi", "neden ", "nasıl ")):
        return "?"
    if any(k in low for k in ("değil", "yoktur", "yok ", "yanlış", "efsane", "sanılanın", "aksine", "asla ", "düşer", "azalır", "kaybolur")):
        return "▼"
    if any(k in low for k in ("tepkime", "elektrik", "enerji", "beyin", "sinir", " nöron", "hız", "saniye", "deney", "ışık", "foton", "lazer", "şok", "dalga")):
        return "⚡"
    if any(k in low for k in ("kat ", "katı", "yüzde", "milyon", "milyar", "derece", "kilometre", "metre", "ton ", "artar", "yükselir", "büyür", "rekor")):
        return "▲"
    if any(k in low for k in ("sayesinde", "korur", "engeller", "keser", "çözüm", "kanıt", "sağlar", "kurtarır", "başarır")):
        return "✔"
    return "!"


def _distill_headline_from_sentence(sent: str, fallback_label: str = "") -> tuple:
    """Cümleden (veya sahne etiketinden) <=20 karakter 2 satır çarpıcı başlık üretir."""
    src = fallback_label.strip() if fallback_label and len(fallback_label.strip()) >= 8 else sent
    # Noktalama temizliği (% ve sayıları koru)
    clean = re.sub(r"[,:;\"'()\[\]—–-]", " ", src)
    clean = re.sub(r"[.!?]+$", "", clean).strip()
    tokens = clean.split()
    # "takip et / yorumlara yaz" kapanış kalıbını ayıkla
    filtered = []
    for t in tokens:
        tl = norm_word(t)
        if tl in ("yorumlara", "yaz", "yazın", "takip", "abone", "unutma"):
            break
        filtered.append(t)
    if len(filtered) >= 2:
        tokens = filtered

    # Önemli kelimeleri (sayılar + anlamlı isim/fiiller) koruyarak 3-5 kelimelik öbek seç
    picked = []
    for t in tokens:
        nw = norm_word(t)
        if not nw:
            continue
        has_digit = any(ch.isdigit() for ch in t)
        if has_digit or (nw not in STOPWORDS_TR and len(nw) >= 3):
            picked.append(t)
        if len(" ".join(picked)) >= 34 or len(picked) >= 5:
            break
    if len(picked) < 2:
        picked = tokens[:4]
    return _wrap_two_lines_20(" ".join(picked), max_chars=20)


def resolve_scene_headlines(cfg: dict, sents: list, n_scenes: int) -> list:
    """Her sahne için `(icon, line1, line2)` listesi döndürür.
    1) `cfg['scene_headlines']` verilmişse doğrudan onu kullanır.
    2) Eski Mira config'i ise `title` + `camera_labels` + `script` cümlelerinden otomatik üretir."""
    explicit = cfg.get("scene_headlines")
    out = []
    if explicit and isinstance(explicit, list):
        for i in range(n_scenes):
            item = explicit[min(i, len(explicit) - 1)]
            if isinstance(item, dict):
                ic = str(item.get("icon") or _classify_semantic_icon("", i, n_scenes))
                l1 = tr_upper(item.get("line1", ""))
                l2 = tr_upper(item.get("line2", ""))
                if not l2:
                    l1, l2 = _wrap_two_lines_20(l1, 20)
            elif isinstance(item, (list, tuple)) and len(item) >= 3:
                ic, l1, l2 = str(item[0]), tr_upper(item[1]), tr_upper(item[2])
            elif isinstance(item, (list, tuple)) and len(item) == 2:
                ic = _classify_semantic_icon(" ".join(item), i, n_scenes)
                l1, l2 = tr_upper(item[0]), tr_upper(item[1])
            else:
                ic = _classify_semantic_icon(str(item), i, n_scenes)
                l1, l2 = _wrap_two_lines_20(str(item), 20)
            if ic not in ("?", "▼", "⚡", "▲", "!", "✔"):
                ic = "!"
            out.append({"icon": ic, "line1": l1[:22], "line2": l2[:22]})
        return out

    raw_lines = _flatten_title_lines(cfg.get("title") or cfg.get("title_lines"))
    cam_labels = cfg.get("camera_labels") or []

    for i in range(n_scenes):
        sent_i = sents[min(i, len(sents) - 1)] if sents else ""
        if i == 0 and raw_lines:
            joined = " ".join(raw_lines)
            if len(raw_lines) == 2 and len(raw_lines[0]) <= 20 and len(raw_lines[1]) <= 20:
                l1, l2 = raw_lines[0], raw_lines[1]
            else:
                l1, l2 = _wrap_two_lines_20(joined, 20)
            ic = "?" if ("?" in sent_i or "?" in joined) else _classify_semantic_icon(sent_i or joined, 0, n_scenes)
        else:
            lbl = cam_labels[i] if i < len(cam_labels) else ""
            # Son sahnede kapanış sorusunu (Peki...?) tercih et
            if i == n_scenes - 1 and sents:
                q_sents = [s for s in sents if "?" in s]
                src_sent = q_sents[-1] if q_sents else sents[-1]
                l1, l2 = _distill_headline_from_sentence(src_sent, "")
                ic = "?"
            else:
                l1, l2 = _distill_headline_from_sentence(sent_i, lbl)
                ic = _classify_semantic_icon(sent_i or lbl, i, n_scenes)
        out.append({"icon": ic, "line1": l1, "line2": l2})
    return out


# ---------------------------------------------------------------- Semantik Sarı İkon Çizici
def draw_semantic_icon(ov: Image.Image, icon_type: str, cx: int, cy: int, alpha: int = 255):
    """Başlık solundaki keskin sarı (#E3F424) vektör ikonu çizer (?, ▼, ⚡, ▲, !, ✔)."""
    d = ImageDraw.Draw(ov)
    yel = (227, 244, 36, alpha)
    shd = (0, 0, 0, int(alpha * 0.78))

    if icon_type in ("?", "!"):
        f_ic = load_font("Poppins-Bold.ttf", S_(94))
        bb = d.textbbox((0, 0), icon_type, font=f_ic)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
        tx = int(cx - tw / 2 - bb[0])
        ty = int(cy - th / 2 - bb[1])
        d.text((tx + S_(4), ty + S_(5)), icon_type, font=f_ic, fill=shd)
        d.text((tx, ty), icon_type, font=f_ic, fill=yel)
    elif icon_type == "▼":
        r = S_(30)
        pts = [(cx - r, cy - int(r * 0.72)), (cx + r, cy - int(r * 0.72)), (cx, cy + int(r * 0.92))]
        d.polygon([(x + S_(4), y + S_(5)) for x, y in pts], fill=shd)
        d.polygon(pts, fill=yel)
    elif icon_type == "▲":
        r = S_(30)
        pts = [(cx, cy - int(r * 0.92)), (cx + r, cy + int(r * 0.72)), (cx - r, cy + int(r * 0.72))]
        d.polygon([(x + S_(4), y + S_(5)) for x, y in pts], fill=shd)
        d.polygon(pts, fill=yel)
    elif icon_type == "⚡":
        s = S_SCALE
        pts = [
            (cx + int(6 * s), cy - int(40 * s)),
            (cx - int(22 * s), cy + int(2 * s)),
            (cx - int(2 * s), cy + int(2 * s)),
            (cx - int(10 * s), cy + int(40 * s)),
            (cx + int(24 * s), cy - int(6 * s)),
            (cx + int(3 * s), cy - int(6 * s)),
        ]
        d.polygon([(x + S_(4), y + S_(5)) for x, y in pts], fill=shd)
        d.polygon(pts, fill=yel)
    elif icon_type == "✔":
        s = S_SCALE
        pts = [
            (cx - int(26 * s), cy + int(2 * s)),
            (cx - int(7 * s), cy + int(22 * s)),
            (cx + int(28 * s), cy - int(22 * s)),
        ]
        d.line([(x + S_(4), y + S_(5)) for x, y in pts], fill=shd, width=S_(13), joint="curve")
        d.line(pts, fill=yel, width=S_(13), joint="curve")


# ---------------------------------------------------------------- 3D Rozet & 3D [TAKİP ET] Butonu
def build_3d_badge() -> Image.Image:
    bw, bh = S_(214), S_(59)
    pad = S_(14)
    im = Image.new("RGBA", (bw + pad * 2, bh + pad * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    x0, y0 = pad, pad
    r = S_(15)
    d.rounded_rectangle([x0 + S_(2), y0 + S_(6), x0 + bw + S_(2), y0 + bh + S_(7)], radius=r, fill=(0, 0, 0, 130))
    d.rounded_rectangle([x0, y0 + S_(4), x0 + bw, y0 + bh + S_(4)], radius=r, fill=BADGE_BEVEL)
    d.rounded_rectangle([x0, y0, x0 + bw, y0 + bh], radius=r, fill=BRAND_YEL)
    d.rounded_rectangle([x0 + S_(3), y0 + S_(2), x0 + bw - S_(3), y0 + S_(14)], radius=S_(10), fill=(247, 255, 135, 95))
    f_tag = load_font("Poppins-Bold.ttf", S_(31))
    txt = "BİLGİ DOZU"
    bb = d.textbbox((0, 0), txt, font=f_tag)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    tx = x0 + (bw - tw) / 2 - bb[0]
    ty = y0 + (bh - th) / 2 - bb[1] - S_(1)
    d.text((tx, ty + S_(1)), txt, font=f_tag, fill=(255, 255, 255, 90))
    d.text((tx, ty), txt, font=f_tag, fill=DARK_TEXT)
    return im


def build_3d_cta_button(pressed: float = 0.0, sheen_pos: float = -1.0) -> Image.Image:
    bw, bh = S_(228), S_(64)
    pad = S_(24)
    im = Image.new("RGBA", (bw + pad * 2, bh + pad * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    press_px = int(round(pressed * S_(4)))
    x0, y0 = pad, pad + press_px
    r = S_(16)
    sh_off = max(S_(2), S_(7) - press_px)
    d.rounded_rectangle([x0 + S_(2), y0 + sh_off, x0 + bw + S_(2), y0 + bh + sh_off + S_(2)],
                        radius=r, fill=(0, 0, 0, 145))
    bev = max(S_(1), S_(5) - press_px)
    d.rounded_rectangle([x0, y0 + bev, x0 + bw, y0 + bh + bev], radius=r, fill=BADGE_BEVEL)
    fill_col = (238, 252, 72, 255) if pressed > 0.3 else BRAND_YEL
    d.rounded_rectangle([x0, y0, x0 + bw, y0 + bh], radius=r, fill=fill_col)
    d.rounded_rectangle([x0 + S_(4), y0 + S_(3), x0 + bw - S_(4), y0 + S_(16)],
                        radius=S_(10), fill=(250, 255, 160, 110))
    f_btn = load_font("Poppins-Bold.ttf", S_(33))
    txt = "TAKİP ET"
    bb = d.textbbox((0, 0), txt, font=f_btn)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    tx = x0 + (bw - tw) / 2 - bb[0]
    ty = y0 + (bh - th) / 2 - bb[1] - S_(1)
    d.text((tx, ty + S_(1)), txt, font=f_btn, fill=(255, 255, 255, 95))
    d.text((tx, ty), txt, font=f_btn, fill=DARK_TEXT)

    if 0.0 <= sheen_pos <= 1.0:
        mask = Image.new("L", im.size, 0)
        md = ImageDraw.Draw(mask)
        md.rounded_rectangle([x0, y0, x0 + bw, y0 + bh], radius=r, fill=255)
        sheen = Image.new("RGBA", im.size, (0, 0, 0, 0))
        sd = ImageDraw.Draw(sheen)
        sx = int(x0 - S_(40) + sheen_pos * (bw + S_(80)))
        pts = [(sx - S_(18), y0), (sx + S_(18), y0), (sx - S_(2), y0 + bh), (sx - S_(38), y0 + bh)]
        sd.polygon(pts, fill=(255, 255, 255, 135))
        sheen = sheen.filter(ImageFilter.GaussianBlur(S_(4)))
        im = Image.composite( Image.alpha_composite(im, sheen), im, mask)
    return im


# ---------------------------------------------------------------- AŞAMA 1: PLATES (Tam Ekran 1080x1920)
def build_plate(src_path: str, out_path: str, dark_bottom_cta: bool = False):
    src = Image.open(src_path).convert("RGB")
    PW, PH = S_(1620), S_(2880)
    sc = max(PW / src.width, PH / src.height)
    nw, nh = int(src.width * sc + 0.5), int(src.height * sc + 0.5)
    img = src.resize((nw, nh), Image.LANCZOS)
    img = img.crop(((nw - PW) // 2, (nh - PH) // 2, (nw - PW) // 2 + PW, (nh - PH) // 2 + PH))
    img = ImageEnhance.Color(img).enhance(1.04)
    img = ImageEnhance.Contrast(img).enhance(1.08)
    img = ImageEnhance.Brightness(img).enhance(0.95)
    img = img.filter(ImageFilter.UnsharpMask(radius=1.8, percent=38, threshold=2))

    arr = np.asarray(img).astype(np.float32) / 255.0
    # Üst başlık okunabilirlik gradyanı (orta ekran %100 parlak kalır)
    ytop = int(PH * 0.25)
    top_g = (np.linspace(1.0, 0.0, ytop, dtype=np.float32) ** 1.65) * 0.62
    arr[:ytop] *= (1.0 - top_g[:, None, None])

    if dark_bottom_cta:
        # Kapanış sahnesinde soru + karaoke + [TAKİP ET] için temiz koyu alt alan (#0A0C10)
        y0 = int(PH * 0.44)
        g_cta = np.clip((np.linspace(0.0, 1.0, PH - y0, dtype=np.float32) ** 1.15) * 0.92, 0.0, 0.94)
        dark_rgb = np.array([10 / 255.0, 12 / 255.0, 16 / 255.0], dtype=np.float32)
        arr[y0:] = arr[y0:] * (1.0 - g_cta[:, None, None]) + dark_rgb[None, None, :] * g_cta[:, None, None]
    else:
        ybot = int(PH * 0.42)
        y0 = PH - ybot
        bot_g = (np.linspace(0.0, 1.0, ybot, dtype=np.float32) ** 1.55) * 0.78
        arr[y0:] *= (1.0 - bot_g[:, None, None])

    ext = os.path.splitext(out_path)[1].lower()
    out_im = Image.fromarray(np.clip(arr * 255.0, 0, 255).astype(np.uint8))
    if ext in (".jpg", ".jpeg"):
        out_im.save(out_path, quality=92)
    else:
        out_im.save(out_path)


def _discover_scenes(work_dir: str, cfg: dict) -> list:
    names = list(cfg.get("scenes") or [])
    if not names:
        for prefix in ("s", "bg"):
            found = []
            for idx in range(1, 10):
                for ext in (".png", ".jpg", ".jpeg", ".webp"):
                    cand = f"{prefix}{idx}{ext}"
                    if os.path.exists(os.path.join(work_dir, cand)):
                        found.append(cand)
                        break
            if found:
                names = found
                break
    if not names:
        raise FileNotFoundError(f"{work_dir} içinde sahne görseli (bg1.png / s1.jpg) bulunamadı.")

    # Eski 1-görselli fallback: bg2 yoksa bg1'den türet
    if len(names) >= 2 and names[1] == "bg2.png":
        p1 = os.path.join(work_dir, names[0])
        p2 = os.path.join(work_dir, "bg2.png")
        if os.path.exists(p1) and not os.path.exists(p2):
            im = Image.open(p1).convert("RGB").transpose(Image.FLIP_LEFT_RIGHT)
            pw, ph = im.size
            im = im.crop((int(pw * 0.08), int(ph * 0.05), int(pw * 0.92), int(ph * 0.88)))
            ImageEnhance.Brightness(im).enhance(0.90).save(p2)
    return names


def stage_plates(vdir_arg: str, explicit_cfg_path: str = None):
    work_dir, cfg, _ = _resolve_context(vdir_arg, explicit_cfg_path)
    names = _discover_scenes(work_dir, cfg)
    for i, n in enumerate(names):
        src = os.path.join(work_dir, n)
        out = os.path.join(work_dir, "plate_" + n)
        build_plate(src, out, dark_bottom_cta=(i == len(names) - 1 and len(names) >= 4))
        print("plate:", out)
    # Kapanış sahnesi için her zaman koyu alt alanlı özel plaka da hazırla
    cta_plate = os.path.join(work_dir, "plate_closing_cta.jpg")
    build_plate(os.path.join(work_dir, names[-1]), cta_plate, dark_bottom_cta=True)


# ---------------------------------------------------------------- AŞAMA 2: TIMING (Nefes Esli VO + Kelime Senkronu + Sahne Planı)
def read_wav_mono(path: str):
    with contextlib.closing(wave.open(path, "rb")) as w:
        fr = w.getframerate()
        ch = w.getnchannels()
        raw = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float64) / 32768.0
        if ch > 1:
            raw = raw.reshape(-1, ch).mean(axis=1)
    return raw, fr


def write_wav_mono(path: str, sig: np.ndarray, fr: int = SR):
    pcm = np.clip(sig * 32767.0, -32768, 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(fr)
        w.writeframes(pcm.tobytes())


def ensure_vo_raw(work_dir: str) -> str:
    raw_wav = os.path.join(work_dir, "vo_raw.wav")
    if os.path.exists(raw_wav) and os.path.getsize(raw_wav) > 1000:
        return raw_wav
    for alt in ("vo_raw.mp3", "vo.mp3", "vo.wav", "vo_raw.m4a", "audio.mp3"):
        p = os.path.join(work_dir, alt)
        if os.path.exists(p):
            subprocess.run([FF, "-y", "-hide_banner", "-loglevel", "error",
                            "-i", p, "-ar", str(SR), "-ac", "1", "-c:a", "pcm_s16le", raw_wav], check=True)
            return raw_wav
    raise FileNotFoundError(f"{work_dir} içinde vo_raw.wav (veya vo.mp3) bulunamadı.")


def ff_silences(path: str, noise_db: float = -35.0, min_dur: float = 0.14):
    r = subprocess.run(
        [FF, "-hide_banner", "-i", path, "-af", f"silencedetect=noise={noise_db}dB:d={min_dur}", "-f", "null", "-"],
        capture_output=True, text=True
    )
    log = r.stderr
    starts = [float(v) for v in re.findall(r"silence_start:\s*([0-9.]+)", log)]
    ends = [float(v) for v in re.findall(r"silence_end:\s*([0-9.]+)", log)]
    mm = re.search(r"Duration:\s*(\d+):(\d+):([0-9.]+)", log)
    dur = (float(mm.group(1)) * 3600 + float(mm.group(2)) * 60 + float(mm.group(3))) if mm else 0.0
    pairs = list(zip(starts, ends))
    if len(starts) > len(ends):
        pairs.append((starts[-1], dur))
    return pairs, dur


def _align_sentences_to_spans(sents: list, spans: list):
    chars = [max(1, len(s)) for s in sents]
    tot_c = sum(chars)
    tot_s = sum(b - a for a, b in spans) or 1.0
    exp = [tot_s * c / tot_c for c in chars]
    m, n = len(spans), len(sents)
    if m < n:
        # Daha az sessizlik varsa orantılı böl
        cur = spans[0][0]
        end_all = spans[-1][1]
        span_tot = max(0.1, end_all - cur)
        res = []
        for c in chars:
            d = span_tot * c / tot_c
            res.append((cur, cur + d))
            cur += d
        return res

    INF = 1e18
    dp = [[INF] * (n + 1) for _ in range(m + 1)]
    bk = [[0] * (n + 1) for _ in range(m + 1)]
    dp[0][0] = 0.0
    for i in range(1, m + 1):
        for j in range(1, min(i, n) + 1):
            for k in range(j - 1, i):
                if dp[k][j - 1] >= INF:
                    continue
                got = sum(b - a for a, b in spans[k:i])
                cost = dp[k][j - 1] + abs(got - exp[j - 1]) + 0.22 * (i - k - 1)
                if cost < dp[i][j]:
                    dp[i][j] = cost
                    bk[i][j] = k
    cuts, i, j = [], m, n
    while j > 0:
        k = bk[i][j]
        cuts.append((k, i))
        i, j = k, j - 1
    cuts.reverse()
    if cuts:
        cuts[0] = (0, cuts[0][1])
    return [(spans[gi][0], spans[gj - 1][1]) for gi, gj in cuts]


def _try_whisper_words(spaced_wav: str, script_words: list):
    """faster-whisper kuruluysa milisaniyelik kelime zamanlaması çıkarır; yoksa None döner."""
    if os.environ.get("MIRA_DISABLE_WHISPER") == "1":
        return None
    try:
        from faster_whisper import WhisperModel
    except Exception:
        return None

    try:
        tmp16 = spaced_wav + ".16k.wav"
        subprocess.run([FF, "-y", "-hide_banner", "-loglevel", "error",
                        "-i", spaced_wav, "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", tmp16], check=True)
        sig16, _ = read_wav_mono(tmp16)
        os.unlink(tmp16)
        model_name = os.environ.get("MIRA_WHISPER_MODEL", "base")
        model = WhisperModel(model_name, device="cpu", compute_type="int8", cpu_threads=2)
        segs, _ = model.transcribe(sig16.astype(np.float32), language="tr", word_timestamps=True, vad_filter=False)
        asr_words = []
        for seg in segs:
            for w in (seg.words or []):
                wt = w.word.strip()
                if wt:
                    asr_words.append({"w": wt, "s": float(w.start), "e": float(w.end)})
        del model
        gc.collect()
        if len(asr_words) < max(3, len(script_words) // 2):
            return None
        return _map_script_to_asr(script_words, asr_words)
    except Exception as exc:
        print(f"[timing] faster-whisper atlandı ({exc}); hece-ağırlıklı hizalama kullanılacak.")
        return None


def _map_script_to_asr(script_words: list, asr_words: list) -> list:
    s_norm = [norm_word(w) for w in script_words]
    a_norm = [norm_word(x["w"]) for x in asr_words]
    sm = difflib.SequenceMatcher(None, s_norm, a_norm, autojunk=False)
    mapped = [None] * len(script_words)

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                aw = asr_words[j1 + k]
                mapped[i1 + k] = {"w": script_words[i1 + k], "s": aw["s"], "e": aw["e"]}
        elif tag in ("replace", "delete") and (j2 > j1):
            t0 = asr_words[j1]["s"]
            t1 = asr_words[j2 - 1]["e"]
            weights = [max(2, len(norm_word(script_words[idx]))) for idx in range(i1, i2)]
            tot_w = sum(weights) or 1
            cur = t0
            for idx, ww in zip(range(i1, i2), weights):
                dur = (t1 - t0) * ww / tot_w
                mapped[idx] = {"w": script_words[idx], "s": cur, "e": cur + dur}
                cur += dur

    # Eşleşmeyen boşlukları komşularından tamamla
    for i in range(len(mapped)):
        if mapped[i] is None:
            prev_e = mapped[i - 1]["e"] if i > 0 and mapped[i - 1] else DEFAULT_INTRO_LEAD
            next_s = None
            for k in range(i + 1, len(mapped)):
                if mapped[k] is not None:
                    next_s = mapped[k]["s"]
                    break
            if next_s is None:
                next_s = prev_e + 0.28
            span = max(0.12, next_s - prev_e)
            mapped[i] = {"w": script_words[i], "s": prev_e, "e": prev_e + min(0.32, span)}
    return mapped


def _syllable_weight(word: str) -> float:
    vowels = sum(1 for ch in tr_lower(word) if ch in "aeıioöuüâîû")
    base = max(1.2, vowels * 1.05 + 0.18 * len(norm_word(word)))
    if any(word.endswith(p) for p in (",", ";", ":")):
        base += 0.45
    elif any(word.endswith(p) for p in (".", "!", "?")):
        base += 0.65
    return base


def wrap_caption_rows(meas: ImageDraw.ImageDraw, words: list, font: ImageFont.FreeTypeFont, maxw: int = None):
    maxw = maxw or S_(930)
    gap = S_(15)
    rows, cur, cw = [], [], 0.0
    for wd in words:
        ww = wlen(meas, wd["w"], font)
        if cur and (cw + gap + ww > maxw):
            rows.append(cur)
            cur, cw = [], 0.0
        cur.append((wd, ww))
        cw += ww + (gap if len(cur) > 1 else 0.0)
    if cur:
        rows.append(cur)
    return rows


def _chunk_sentence_words(sent_words: list, meas: ImageDraw.ImageDraw, font: ImageFont.FreeTypeFont) -> list:
    """Cümle kelimelerini en fazla 2 satır (<=7 kelime) okunaklı altyazı bloklarına böler."""
    if not sent_words:
        return []
    groups, cur = [], []
    for wd in sent_words:
        cur.append(wd)
        rows_try = wrap_caption_rows(meas, cur, font, S_(930))
        punct_break = wd["w"].endswith((",", ";", ":")) and len(cur) >= 4
        if len(rows_try) > 2:
            last = cur.pop()
            if cur:
                groups.append(cur)
            cur = [last]
        elif punct_break or len(cur) >= 7:
            groups.append(cur)
            cur = []
    if cur:
        if groups and len(cur) <= 2 and len(wrap_caption_rows(meas, groups[-1] + cur, font, S_(930))) <= 2:
            groups[-1].extend(cur)
        else:
            groups.append(cur)
    return groups


def stage_timing(vdir_arg: str, explicit_cfg_path: str = None):
    work_dir, cfg, _ = _resolve_context(vdir_arg, explicit_cfg_path)
    script_path = os.path.join(work_dir, "script.txt")
    script = open(script_path, encoding="utf-8").read().strip()
    raw_wav = ensure_vo_raw(work_dir)

    # Ham sesi vo_final.wav olarak bit-birebir koru (SHA256 ses bütünlüğü garantisi)
    vo_final = os.path.join(work_dir, "vo_final.wav")
    if os.path.abspath(raw_wav) != os.path.abspath(vo_final):
        shutil.copyfile(raw_wav, vo_final)

    x_raw, fr = read_wav_mono(raw_wav)
    if fr != SR:
        subprocess.run([FF, "-y", "-hide_banner", "-loglevel", "error",
                        "-i", raw_wav, "-ar", str(SR), "-ac", "1", "-c:a", "pcm_s16le", vo_final], check=True)
        x_raw, fr = read_wav_mono(vo_final)

    dur_raw = len(x_raw) / float(fr)
    sils, _ = ff_silences(vo_final, noise_db=-35.0, min_dur=0.13)

    # Baş/son boşluğu kırpılmış konuşma aralıkları
    spans, prev = [], 0.0
    for s, e in sils:
        if s - prev > 0.18:
            spans.append((prev, s))
        prev = e
    if dur_raw - prev > 0.18:
        spans.append((prev, dur_raw))
    if not spans:
        spans = [(0.0, dur_raw)]

    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", script) if s.strip()]
    if not sents:
        sents = [script]
    sent_raw_spans = _align_sentences_to_spans(sents, spans)

    intro_lead = float(cfg.get("intro_lead", DEFAULT_INTRO_LEAD))
    pause_target = float(cfg.get("sentence_pause", DEFAULT_SENT_PAUSE))
    outro_hold = float(cfg.get("outro_hold", DEFAULT_OUTRO_HOLD))

    # Konuşulan hiçbir kelimeye dokunmadan YALNIZCA cümle arası doğal sessizlik ortalarından
    # keserek 1.45s intro + ~0.62s cümle arası nefes + 1.45s outro içeren vo_spaced.wav üret!
    fade_n = int(0.012 * fr)
    pieces = [np.zeros(int(round(intro_lead * fr)), dtype=np.float64)]
    spaced_sent_spans = []
    cursor_samples = len(pieces[0])

    # Cümle sınırlarını tam sessizlik ortasından al
    cut_points = [max(0, int(round((sent_raw_spans[0][0] - 0.03) * fr)))]
    for idx in range(len(sent_raw_spans) - 1):
        end_cur = sent_raw_spans[idx][1]
        start_nxt = sent_raw_spans[idx + 1][0]
        mid = 0.5 * (end_cur + start_nxt)
        cut_points.append(min(len(x_raw), max(cut_points[-1], int(round(mid * fr)))))
    cut_points.append(min(len(x_raw), int(round((sent_raw_spans[-1][1] + 0.05) * fr))))

    for si in range(len(sents)):
        s_smp, e_smp = cut_points[si], cut_points[si + 1]
        seg = x_raw[s_smp:e_smp].copy()
        # Kenarlarda mikro-tıklama önleyici 12ms yumuşak zarf
        if len(seg) > fade_n * 3:
            seg[:fade_n] *= np.linspace(0.0, 1.0, fade_n)
            seg[-fade_n:] *= np.linspace(1.0, 0.0, fade_n)
        t_start = cursor_samples / float(fr)
        pieces.append(seg)
        cursor_samples += len(seg)
        t_end = cursor_samples / float(fr)
        spaced_sent_spans.append((t_start, t_end))

        if si < len(sents) - 1:
            # Mevcut doğal boşluğa ek olarak toplam ~0.62 sn temiz cümle nefesi bırak
            natural_tail = max(0.0, (e_smp / float(fr)) - sent_raw_spans[si][1])
            natural_head_next = max(0.0, sent_raw_spans[si + 1][0] - (e_smp / float(fr)))
            extra_pause = max(0.18, pause_target - (natural_tail + natural_head_next))
            p_smp = int(round(extra_pause * fr))
            pieces.append(np.zeros(p_smp, dtype=np.float64))
            cursor_samples += p_smp

    pieces.append(np.zeros(int(round(outro_hold * fr)), dtype=np.float64))
    vo_spaced = np.concatenate(pieces)
    spaced_path = os.path.join(work_dir, "vo_spaced.wav")
    write_wav_mono(spaced_path, vo_spaced, fr)
    total_dur = round(len(vo_spaced) / float(fr), 2)

    # Kelime zamanlaması: faster-whisper varsa ASR, yoksa cümle içi hece-ağırlıklı hizalama
    all_script_words = [w for s in sents for w in s.split()]
    whisper_mapped = _try_whisper_words(spaced_path, all_script_words)

    sent_word_lists = []
    if whisper_mapped and len(whisper_mapped) == len(all_script_words):
        ptr = 0
        for s in sents:
            cnt = len(s.split())
            sent_word_lists.append(whisper_mapped[ptr:ptr + cnt])
            ptr += cnt
    else:
        for s, (st_s, en_s) in zip(sents, spaced_sent_spans):
            ws = s.split()
            weights = [_syllable_weight(w) for w in ws]
            tot_w = sum(weights) or 1.0
            usable = max(0.15, (en_s - st_s) - 0.04)
            cur_t = st_s + 0.02
            w_objs = []
            for w_txt, ww in zip(ws, weights):
                wd = usable * ww / tot_w
                w_objs.append({"w": w_txt, "s": round(cur_t, 3), "e": round(cur_t + wd, 3)})
                cur_t += wd
            sent_word_lists.append(w_objs)

    meas = ImageDraw.Draw(Image.new("RGB", (16, 16)))
    f_cap = load_font("Poppins-Bold.ttf", S_(52))

    chunks = []
    for si, w_objs in enumerate(sent_word_lists):
        for grp in _chunk_sentence_words(w_objs, meas, f_cap):
            rows_wrapped = wrap_caption_rows(meas, grp, f_cap, S_(930))
            chunks.append({
                "sent_idx": si,
                "text": " ".join(x["w"] for x in grp),
                "words": [{"w": x["w"], "s": round(x["s"], 3), "e": round(x["e"], 3)} for x in grp],
                "show": round(max(0.0, grp[0]["s"] - 0.08), 3),
                "hide": round(grp[-1]["e"] + 0.24, 3),
                "rows": rows_wrapped,
            })

    for ci in range(len(chunks) - 1):
        chunks[ci]["hide"] = round(min(chunks[ci]["hide"], chunks[ci + 1]["show"] - 0.01), 3)
    if chunks:
        # Son altyazı bloğu [TAKİP ET] butonuyla birlikte kısa süre daha ekranda kalsın
        chunks[-1]["hide"] = round(min(total_dur - 0.25, chunks[-1]["words"][-1]["e"] + 0.95), 3)

    last_word_end = chunks[-1]["words"][-1]["e"] if chunks else round(total_dur - outro_hold, 3)

    # Sahne zaman çizelgesi (2..7 sahne otomatik eşleme)
    scene_files = _discover_scenes(work_dir, cfg)
    n_sc = len(scene_files)
    headlines = resolve_scene_headlines(cfg, sents, n_sc)

    scene_timeline = []
    for si in range(n_sc):
        # Cümle indeksini sahne indeksine orantılı eşle
        sent_idx_start = min(len(spaced_sent_spans) - 1, int(round(si * len(spaced_sent_spans) / n_sc)))
        sent_idx_end = min(len(spaced_sent_spans) - 1, max(sent_idx_start, int(round((si + 1) * len(spaced_sent_spans) / n_sc)) - 1))
        t0 = 0.0 if si == 0 else max(0.0, spaced_sent_spans[sent_idx_start][0] - 0.18)
        t1 = total_dur if si == n_sc - 1 else max(t0 + 1.0, spaced_sent_spans[sent_idx_end][1] + 0.20)
        scene_timeline.append({
            "scene_idx": si,
            "file": scene_files[si],
            "is_closing": (si == n_sc - 1),
            "start": round(t0, 3),
            "end": round(t1, 3),
            "icon": headlines[si]["icon"],
            "line1": headlines[si]["line1"],
            "line2": headlines[si]["line2"],
        })
    for si in range(len(scene_timeline) - 1):
        scene_timeline[si + 1]["start"] = scene_timeline[si]["end"]

    # Onaylı Saf 3D Kapanış Ekranı: "Daha fazla Bilgi Dozu..." cümlesine girer girmez kararır,
    # tam "takip et!" dendiği anda fare butona tıklar!
    flat_words = [wd for ch in chunks for wd in ch["words"]]
    cta_start, click_delay = endcard_v2.find_endcard_and_click_times(flat_words, last_word_end)
    for ch in chunks:
        if ch["show"] >= cta_start - 0.05:
            ch["hide"] = ch["show"]  # Kapanış cümlesinde altyazı gösterilmez, sadece animasyon!
        elif ch["hide"] > cta_start:
            ch["hide"] = round(cta_start, 3)

    out = {
        "template_version": "2.2",
        "fps": FPS,
        "total": total_dur,
        "vo_dur": round(dur_raw, 3),
        "vo_file": "vo_spaced.wav",
        "vo_raw_preserved": "vo_final.wav",
        "intro_lead": intro_lead,
        "sentence_pause": pause_target,
        "outro_hold": outro_hold,
        "last_end": round(last_word_end, 3),
        "cta_start": round(cta_start, 3),
        "cta_click_delay": round(click_delay, 3),
        "scene_switch": round(total_dur * 0.48, 2),
        "scenes": scene_timeline,
        "sentence_spans": [[round(a, 3), round(b, 3)] for a, b in spaced_sent_spans],
        "chunks": chunks,
    }
    json.dump(out, open(os.path.join(work_dir, "timing.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"{vdir_arg}: v2 timing hazır -> {len(chunks)} altyazı bloğu, {n_sc} sahne, toplam {total_dur:.2f}s, CTA @ {cta_start:.2f}s")


# ---------------------------------------------------------------- AŞAMA 3: MUSIC (Telefon Hoparlöründe Net Duyulan Bilgi Dozu Jeneriği)
THEME_ROOT_SHIFTS = {
    "gunluk_bilim": 0,     # E minor (orijinal Bilgi Dozu jeneriği)
    "uzay": -2,            # D Dorian / minor
    "insan_beyin": 2,      # F# minor
    "doga_hayvan": 5,      # A minor
    "tarih_teknoloji": -3, # C# minor
}


def synthesize_bilgidozu_jenerik(dur_sec: float, sr: int = SR, semitone_shift: int = 0) -> np.ndarray:
    """220 Hz - 2.8 kHz bandında zengin harmonikli, telefon ve laptop hoparlöründe
    net duyulan stereo Bilgi Dozu belgesel/bilim jenerik müziği."""
    n = int(dur_sec * sr) + sr
    t = np.arange(n, dtype=np.float64) / sr
    bpm = 112.0
    beat = 60.0 / bpm
    bar = beat * 4.0
    pitch_mul = 2.0 ** (semitone_shift / 12.0)

    # 1) Sıcak harmonik akor pedi (Em9 -> Cmaj7 -> G6 -> Dadd9)
    prog = [
        (164.81, 246.94, 329.63, 392.00, 493.88),
        (130.81, 196.00, 261.63, 329.63, 392.00),
        (196.00, 246.94, 293.66, 392.00, 493.88),
        (146.83, 220.00, 293.66, 369.99, 440.00),
    ]
    bar_idx = (np.floor(t / bar).astype(int)) % 4
    pad_l = np.zeros(n, dtype=np.float64)
    pad_r = np.zeros(n, dtype=np.float64)
    for bi, chord in enumerate(prog):
        mask = (bar_idx == bi).astype(np.float64)
        local_t = np.mod(t, bar)
        sw = np.minimum(1.0, local_t / 0.18) * np.minimum(1.0, (bar - local_t) / 0.18)
        env = mask * sw
        for ni, f0 in enumerate(chord):
            f = f0 * pitch_mul
            sig = (0.58 * np.sin(2 * np.pi * f * t)
                   + 0.26 * np.sin(2 * np.pi * (f * 2.0) * t + 0.3)
                   + 0.10 * np.sin(2 * np.pi * (f * 3.0) * t + 0.7))
            pan = 0.35 + 0.30 * ((ni % 3) / 2.0)
            pad_l += env * sig * (1.0 - pan * 0.45) * 0.055
            pad_r += env * sig * (0.55 + pan * 0.45) * 0.055

    # 2) Karakteristik Bilgi Dozu bilimsel marimba/synth arpej motifi (580 - 1180 Hz)
    motif_hz = [659.25, 783.99, 987.77, 880.00, 659.25, 783.99, 739.99, 587.33]
    step = beat / 2.0
    n_steps = int(dur_sec / step) + 2
    arp_l = np.zeros(n, dtype=np.float64)
    arp_r = np.zeros(n, dtype=np.float64)
    for si in range(n_steps):
        t0 = si * step
        i0 = int(t0 * sr)
        ln = int(0.30 * sr)
        if i0 + ln >= n:
            break
        tt = np.arange(ln, dtype=np.float64) / sr
        f = motif_hz[si % len(motif_hz)] * pitch_mul
        if (si // 16) % 2 == 1 and si % 4 == 2:
            f *= 1.12246
        env = (1.0 - np.exp(-tt * 140.0)) * np.exp(-tt * 9.5)
        tone = (0.68 * np.sin(2 * np.pi * f * tt)
                + 0.24 * np.sin(2 * np.pi * 2.0 * f * tt)
                + 0.08 * np.sin(2 * np.pi * 3.0 * f * tt) * np.exp(-tt * 22.0))
        acc = 1.18 if (si % 4 == 0) else (0.92 if si % 2 == 0 else 0.72)
        pan_l = 0.85 if (si % 2 == 0) else 0.55
        pan_r = 0.55 if (si % 2 == 0) else 0.85
        arp_l[i0:i0 + ln] += tone * env * 0.145 * acc * pan_l
        arp_r[i0:i0 + ln] += tone * env * 0.145 * acc * pan_r

    # 3) Sıcak bas yürüyüşü (110 - 330 Hz üst harmonikli -> küçük hoparlörde duyulur)
    bass_roots = [82.41, 65.41, 98.00, 73.42]
    bass = np.zeros(n, dtype=np.float64)
    n_beats = int(dur_sec / beat) + 2
    for bi in range(n_beats):
        i0 = int(bi * beat * sr)
        ln = int(0.46 * sr)
        if i0 + ln >= n:
            break
        tt = np.arange(ln, dtype=np.float64) / sr
        bf = bass_roots[(bi // 4) % 4] * pitch_mul
        env = (1.0 - np.exp(-tt * 90.0)) * np.exp(-tt * 5.2)
        b_sig = (0.42 * np.sin(2 * np.pi * bf * tt)
                 + 0.40 * np.sin(2 * np.pi * (bf * 2.0) * tt)
                 + 0.18 * np.sin(2 * np.pi * (bf * 3.0) * tt))
        bass[i0:i0 + ln] += b_sig * env * 0.155

    # 4) Yumuşak belgesel nabız kick + shaker/hi-hat
    perc = np.zeros(n, dtype=np.float64)
    rng = np.random.default_rng(202611 + semitone_shift)
    for bi in range(n_beats):
        i0 = int(bi * beat * sr)
        ln = int(0.16 * sr)
        if i0 + ln < n:
            tt = np.arange(ln, dtype=np.float64) / sr
            f_sw = 56.0 + 95.0 * np.exp(-tt * 38.0)
            ph = 2 * np.pi * np.cumsum(f_sw) / sr
            perc[i0:i0 + ln] += np.sin(ph) * np.exp(-tt * 19.0) * 0.135
        for sub in (0.0, 0.5):
            h0 = int((bi + sub) * beat * sr)
            hln = int(0.045 * sr)
            if h0 + hln < n:
                ht = np.arange(hln, dtype=np.float64) / sr
                nz = rng.standard_normal(hln)
                nz = np.diff(nz, prepend=0.0)
                amp = 0.030 if sub == 0.5 else 0.018
                perc[h0:h0 + hln] += nz * np.exp(-ht * 65.0) * amp

    # 5) Açılış jenerik parıltısı (ilk 1.25 sn içinde nazik yükselen akor vurgusu)
    intro_len = min(n, int(1.25 * sr))
    it = np.arange(intro_len, dtype=np.float64) / sr
    chime = (np.sin(2 * np.pi * 659.25 * pitch_mul * it) * 0.45
             + np.sin(2 * np.pi * 987.77 * pitch_mul * it) * 0.35
             + np.sin(2 * np.pi * 1318.5 * pitch_mul * it) * 0.20)
    c_env = (1.0 - np.exp(-it * 35.0)) * np.exp(-it * 2.6) * 0.11
    arp_l[:intro_len] += chime * c_env
    arp_r[:intro_len] += chime * c_env * 0.92

    left = pad_l + arp_l + bass + perc
    right = pad_r + arp_r + bass + perc
    out = np.stack([left[:int(dur_sec * sr)], right[:int(dur_sec * sr)]], axis=1)
    rms = float(np.sqrt(np.mean(out ** 2)) + 1e-9)
    out = out * (0.175 / rms)  # ~ -15.1 dBFS tam jenerik referans seviyesi
    return np.clip(out, -0.92, 0.92)


def synthesize_cta_sfx(click_delay: float = 1.25, sr: int = SR) -> np.ndarray:
    """Onaylı 3D Kapanış Kartı SFX: yumuşak giriş pop + gerçek fare çift tık + A5->E6 onay tınısı."""
    return endcard_v2.synthesize_endcard_sfx(click_delay=click_delay, sr=sr)


def stage_music(vdir_arg: str, explicit_cfg_path: str = None):
    work_dir, cfg, _ = _resolve_context(vdir_arg, explicit_cfg_path)
    tl_path = os.path.join(work_dir, "timing.json")
    dur = json.load(open(tl_path, encoding="utf-8"))["total"] if os.path.exists(tl_path) else 42.0
    theme_key = str(cfg.get("music_theme") or "gunluk_bilim")
    shift = THEME_ROOT_SHIFTS.get(theme_key, 0)
    st = synthesize_bilgidozu_jenerik(dur + 0.5, sr=SR, semitone_shift=shift)
    out_p = os.path.join(work_dir, "music.wav")
    pcm = np.clip(st[:int(dur * SR)] * 32767.0, -32768, 32767).astype(np.int16)
    with wave.open(out_p, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(pcm.tobytes())
    print(f"music [v2 jenerik | theme={theme_key} | shift={shift:+d} st]: {out_p} ({dur:.2f}s)")


def _one_pole_lpf_stereo(st: np.ndarray, cutoff_hz: float = 850.0, sr: int = SR) -> np.ndarray:
    rc = 1.0 / (2.0 * math.pi * cutoff_hz)
    dt = 1.0 / sr
    alpha = dt / (rc + dt)
    out = np.empty_like(st)
    yl, yr = 0.0, 0.0
    c0, c1 = st[:, 0], st[:, 1]
    o0, o1 = out[:, 0], out[:, 1]
    one_m = 1.0 - alpha
    for i in range(len(st)):
        yl = yl * one_m + c0[i] * alpha
        yr = yr * one_m + c1[i] * alpha
        o0[i] = yl
        o1[i] = yr
    return out


def _measure_lufs(wav_path: str) -> float:
    r = subprocess.run([FF, "-hide_banner", "-i", wav_path, "-af", "ebur128", "-f", "null", "-"],
                       capture_output=True, text=True)
    ms = re.findall(r"I:\s*(-?[0-9.]+)\s*LUFS", r.stderr)
    return float(ms[-1]) if ms else -16.0


def build_mix(work_dir: str, tl: dict) -> str:
    """Onaylı deneme8 / v2 Broadcast Auto-Ducking Miksaj:
    - 0..1.45s tam ses jenerik intro
    - Konuşma anında 50ms look-ahead, -15.6 dB ducking + 850 Hz LPF
    - Cümle arası ~0.62s nefeslerde ve +1.45s outro'da yumuşak müzik yükselişi
    - Sabit lineer -14.2 LUFS kalibrasyon (dinamik AGC düzleştirmesi YOK!)"""
    total = float(tl["total"])
    n_tot = int(round(total * SR))
    vo_file = os.path.join(work_dir, tl.get("vo_file", "vo_spaced.wav"))
    if not os.path.exists(vo_file):
        vo_file = os.path.join(work_dir, "vo_final.wav")
    vo_mono, _ = read_wav_mono(vo_file)
    if len(vo_mono) < n_tot:
        vo_mono = np.pad(vo_mono, (0, n_tot - len(vo_mono)))
    else:
        vo_mono = vo_mono[:n_tot]

    # Konuşma tepe/RMS normalizasyonu (temiz, doğal tok tını)
    sp_rms = float(np.sqrt(np.mean(vo_mono[np.abs(vo_mono) > 0.015] ** 2)) + 1e-9)
    vo_mono = np.clip(vo_mono * (0.205 / sp_rms), -0.88, 0.88)

    mus_path = os.path.join(work_dir, "music.wav")
    if not os.path.exists(mus_path):
        mus = synthesize_bilgidozu_jenerik(total, sr=SR, semitone_shift=0)
    else:
        with contextlib.closing(wave.open(mus_path, "rb")) as wf:
            ch = wf.getnchannels()
            raw = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).astype(np.float64) / 32768.0
            mus = raw.reshape(-1, ch) if ch == 2 else np.stack([raw, raw], axis=1)
    if len(mus) < n_tot:
        reps = int(math.ceil(n_tot / max(1, len(mus))))
        mus = np.tile(mus, (reps, 1))[:n_tot]
    else:
        mus = mus[:n_tot]

    # Zarflı 50ms look-ahead konuşma dedektörü (70ms attack / 140ms release)
    win = int(0.025 * SR)
    env_sq = np.convolve(vo_mono ** 2, np.ones(win) / win, mode="same")
    env_rms = np.sqrt(np.maximum(env_sq, 0.0))
    active = (env_rms > 0.012).astype(np.float64)
    # 50ms look-ahead + 90ms kuyruk tutma (hece arası dalgalanmayı önler, 0.62s cümle esinde açılır)
    la = int(0.050 * SR)
    hold = int(0.090 * SR)
    ker = np.ones(la + hold, dtype=np.float64)
    gate = (np.convolve(np.pad(active, (hold, la)), ker, mode="valid")[:n_tot] > 0.5).astype(np.float64)

    att_a = math.exp(-1.0 / (0.070 * SR))
    rel_a = math.exp(-1.0 / (0.140 * SR))
    duck_curve = np.empty(n_tot, dtype=np.float64)
    g = 0.0
    for i in range(n_tot):
        target = gate[i]
        g = att_a * g + (1.0 - att_a) * target if target > g else rel_a * g + (1.0 - rel_a) * target
        duck_curve[i] = g

    mus_lpf = _one_pole_lpf_stereo(mus, cutoff_hz=850.0, sr=SR)
    gain_vec = 1.0 - duck_curve * (1.0 - DUCK_FLOOR)
    # Konuşma yokken parlak tam spektrum, konuşma varken %85 850Hz LPF + -15.6 dB ducked
    mus_ducked = (
        mus * ((1.0 - 0.85 * duck_curve) * gain_vec)[:, None]
        + mus_lpf * ((0.85 * duck_curve) * gain_vec)[:, None]
    )

    # Son 0.45 sn temiz müzik fade-out
    fo = min(n_tot, int(0.45 * SR))
    mus_ducked[-fo:] *= np.linspace(1.0, 0.0, fo)[:, None]

    mix_st = np.stack([vo_mono, vo_mono], axis=1) + mus_ducked

    # [TAKİP ET] pop + click SFX ekle ("takip et!" anına kilitli)
    cta_t = float(tl.get("cta_start", max(1.0, total - 2.6)))
    click_delay = float(tl.get("cta_click_delay", 1.25))
    sfx = synthesize_cta_sfx(click_delay=click_delay, sr=SR)
    s0 = int(round(cta_t * SR))
    if 0 <= s0 < n_tot:
        s1 = min(n_tot, s0 + len(sfx))
        mix_st[s0:s1] += sfx[:s1 - s0]

    # Sabit lineer -14.2 LUFS kalibrasyon (tek geçişli loudnorm AGC kullanılmaz!)
    mix_path = os.path.join(work_dir, "mix.wav")
    tmp_path = os.path.join(work_dir, "mix_pre.wav")
    peak_pre = float(np.max(np.abs(mix_st)) + 1e-9)
    if peak_pre > 0.89:
        mix_st *= (0.89 / peak_pre)
    pcm_pre = np.clip(mix_st * 32767.0, -32768, 32767).astype(np.int16)
    with wave.open(tmp_path, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(pcm_pre.tobytes())

    cur_lufs = _measure_lufs(tmp_path)
    os.unlink(tmp_path)
    lin_gain = 10.0 ** ((TARGET_LUFS - cur_lufs) / 20.0)
    mix_st *= lin_gain
    # Yumuşak -1.0 dBTP tavan koruyucu
    ceil = 0.891
    over = np.abs(mix_st) > ceil
    if np.any(over):
        mix_st = np.tanh(mix_st / ceil) * ceil

    pcm_final = np.clip(mix_st * 32767.0, -32768, 32767).astype(np.int16)
    with wave.open(mix_path, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(pcm_final.tobytes())

    # Ses kalite telemetrisi kaydet
    intro_n = min(n_tot, int(1.30 * SR))
    intro_rms = 20.0 * math.log10(float(np.sqrt(np.mean((mus_ducked[:intro_n] * lin_gain) ** 2))) + 1e-9)
    sp_mask = gate > 0.5
    duck_rms = 20.0 * math.log10(float(np.sqrt(np.mean((mus_ducked[sp_mask] * lin_gain) ** 2))) + 1e-9) if np.any(sp_mask) else -30.0
    final_lufs = _measure_lufs(mix_path)
    json.dump({
        "integrated_lufs": round(final_lufs, 2),
        "intro_music_dbfs": round(intro_rms, 2),
        "speech_music_dbfs": round(duck_rms, 2),
        "ducking_amount_db": round(intro_rms - duck_rms, 2),
    }, open(os.path.join(work_dir, "audio_qc.json"), "w", encoding="utf-8"), indent=2)
    return mix_path


# ---------------------------------------------------------------- AŞAMA 4: RENDER (Onaylı v2 Görsel Şablon)
def _warp_plate(pl: Image.Image, scene_idx: int, prog: float) -> Image.Image:
    p = 0.80 * prog + 0.20 * ease_io(prog)
    if scene_idx % 2 == 0:
        z = 1.045 + 0.065 * p
        dx = S_(-18) + S_(36) * p
        dy = S_(-24) + S_(32) * p
    else:
        z = 1.110 - 0.060 * p
        dx = S_(18) - S_(36) * p
        dy = S_(20) - S_(32) * p
    sc = (pl.width / z) / W
    left = max(0.0, min(pl.width - W * sc, pl.width / 2.0 + dx - (W / 2.0) * sc))
    top = max(0.0, min(pl.height - H * sc, pl.height / 2.0 + dy - (H / 2.0) * sc))
    return pl.transform((W, H), Image.AFFINE, (sc, 0.0, left, 0.0, sc, top), resample=Image.BICUBIC)


def _scene_bg_at(plates_by_idx: list, closing_plate: Image.Image, scenes_tl: list, tsec: float) -> tuple:
    si = 0
    for idx, sc in enumerate(scenes_tl):
        if tsec >= sc["start"]:
            si = idx
    sc_cur = scenes_tl[si]
    dur_cur = max(0.2, sc_cur["end"] - sc_cur["start"])
    prog_cur = clamp01((tsec - sc_cur["start"]) / dur_cur)
    pl_cur = closing_plate if sc_cur.get("is_closing") else plates_by_idx[si]
    im_cur = _warp_plate(pl_cur, si, prog_cur)

    trans = 0.26
    since = tsec - sc_cur["start"]
    if si > 0 and since < trans:
        sc_prev = scenes_tl[si - 1]
        pl_prev = plates_by_idx[si - 1]
        im_prev = _warp_plate(pl_prev, si - 1, 1.0)
        im_cur = Image.blend(im_prev, im_cur, ease_io(since / trans))
    return im_cur, si, since


def _fit_headline_font(meas: ImageDraw.ImageDraw, line1: str, line2: str) -> ImageFont.FreeTypeFont:
    max_text_w = W - S_(154) - S_(92)  # sol/sağ kenar + ikon alanı
    sz = S_(62)
    while sz > S_(44):
        f = load_font("Poppins-Bold.ttf", sz)
        if max(wlen(meas, line1, f), wlen(meas, line2, f)) <= max_text_w:
            return f
        sz -= 2
    return load_font("Poppins-Bold.ttf", S_(44))


def render_video(vdir_arg: str, explicit_cfg_path: str = None):
    work_dir, cfg, _ = _resolve_context(vdir_arg, explicit_cfg_path)
    tl = json.load(open(os.path.join(work_dir, "timing.json"), encoding="utf-8"))
    total = float(tl["total"])
    NF = max(1, int(round(total * FPS)))

    scenes_tl = tl.get("scenes") or []
    if not scenes_tl:
        raise RuntimeError("timing.json içinde v2 'scenes' zaman çizelgesi eksik; önce `timing` çalıştırın.")

    plates_by_idx = []
    for sc in scenes_tl:
        pp = os.path.join(work_dir, "plate_" + sc["file"])
        if not os.path.exists(pp):
            build_plate(os.path.join(work_dir, sc["file"]), pp, dark_bottom_cta=False)
        plates_by_idx.append(Image.open(pp).convert("RGB"))

    cta_pp = os.path.join(work_dir, "plate_closing_cta.jpg")
    if not os.path.exists(cta_pp):
        build_plate(os.path.join(work_dir, scenes_tl[-1]["file"]), cta_pp, dark_bottom_cta=True)
    closing_plate = Image.open(cta_pp).convert("RGB")

    mix_path = build_mix(work_dir, tl)
    out_mp4 = os.path.join(work_dir, "video.mp4")

    # Statik katman önbellekleri (hız & düşük RAM için)
    badge_im = build_3d_badge()
    btn_idle = build_3d_cta_button(pressed=0.0, sheen_pos=-1.0)
    meas = ImageDraw.Draw(Image.new("RGB", (16, 16)))
    f_cap = load_font("Poppins-Bold.ttf", S_(52))
    f_brand = load_font("Poppins-Bold.ttf", S_(46))
    f_note1 = load_font("Poppins-SemiBold.ttf", S_(23))
    f_note2 = load_font("Poppins-Regular.ttf", S_(20))

    note1_txt = str(cfg.get("note1") or "Kaynak: Bilimsel Araştırma Arşivi")
    note2_txt = str(cfg.get("note2") or "Görseller temsilîdir.")
    while wlen(meas, note1_txt, f_note1) > W - S_(120) and f_note1.size > S_(15):
        f_note1 = load_font("Poppins-SemiBold.ttf", f_note1.size - 1)

    headline_fonts = [_fit_headline_font(meas, sc["line1"], sc["line2"]) for sc in scenes_tl]

    # Yeniden sarmalanmış altyazı satırları (JSON'dan okunurken tuple/float uyumu)
    for ch in tl["chunks"]:
        ch["_rows"] = wrap_caption_rows(meas, ch["words"], f_cap, S_(930))

    brand_w1 = wlen(meas, "BİLGİ ", f_brand)
    brand_w2 = wlen(meas, "DOZU", f_brand)
    brand_tot = brand_w1 + brand_w2

    cta_start = float(tl.get("cta_start", max(1.0, total - 2.6)))
    cta_click_delay = float(tl.get("cta_click_delay", 1.25))

    cmd = [
        FF, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
        "-i", mix_path, "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
        "-maxrate", "3800k", "-bufsize", "7600k", "-threads", "2",
        "-pix_fmt", "yuv420p", "-profile:v", "high",
        "-c:a", "aac", "-b:a", "192k", "-ar", str(SR),
        "-movflags", "+faststart", "-shortest", out_mp4,
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    bar_x0, bar_x1 = S_(79), S_(1043)
    bar_y0, bar_y1 = S_(48), S_(56)
    bar_w = bar_x1 - bar_x0

    for fi in range(NF):
        tsec = fi / float(FPS)
        bg, si, since_scene = _scene_bg_at(plates_by_idx, closing_plate, scenes_tl, tsec)
        bg = endcard_v2.blur_bg_for_endcard(bg, tsec, cta_start, W=W)
        ui_mul = endcard_v2.ui_fade_multiplier(tsec, cta_start)

        ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(ov)

        # Kapanış cümlesi ("Daha fazla Bilgi Dozu...") başladığında üstteki yeşil çubuk ve
        # alttaki kaynak dahil TÜM arayüz söner; ekranda SADECE 3D animasyon kalır!
        if ui_mul > 0.02:
            # 1) Üst İlerleme Çubuğu (x=79..1043, y=48..56)
            prog = clamp01(fi / max(1, NF - 1))
            d.rounded_rectangle([bar_x0, bar_y0, bar_x1, bar_y1], radius=S_(4), fill=(255, 255, 255, int(58 * ui_mul)))
            fw = int(round(bar_w * prog))
            if fw > S_(6):
                glow = Image.new("RGBA", (W, S_(90)), (0, 0, 0, 0))
                gd = ImageDraw.Draw(glow)
                gd.rounded_rectangle([bar_x0, bar_y0 - S_(2), bar_x0 + fw, bar_y1 + S_(2)],
                                     radius=S_(5), fill=(217, 243, 38, int(105 * ui_mul)))
                ov.alpha_composite(glow.filter(ImageFilter.GaussianBlur(S_(5))), (0, 0))
                d.rounded_rectangle([bar_x0, bar_y0, bar_x0 + fw, bar_y1], radius=S_(4), fill=(217, 243, 38, int(255 * ui_mul)))

            # 2) 3D Kabartmalı "BİLGİ DOZU" Rozeti (x=77, y=80)
            if ui_mul >= 0.98:
                ov.alpha_composite(badge_im, (S_(77) - S_(14), S_(80) - S_(14)))
            else:
                b_tmp = badge_im.copy()
                b_tmp.putalpha(b_tmp.getchannel("A").point(lambda v: int(v * ui_mul)))
                ov.alpha_composite(b_tmp, (S_(77) - S_(14), S_(80) - S_(14)))

            # 3) Dinamik Sahne Başlığı + Semantik Sarı İkon (y=287..430)
            sc_obj = scenes_tl[si]
            e_hd = ease_out(since_scene / 0.20) if si > 0 else ease_out((tsec - 0.05) / 0.25)
            if e_hd > 0.01:
                al_h = int(255 * e_hd * ui_mul)
                dy_h = int(round((1.0 - e_hd) * S_(14)))
                draw_semantic_icon(ov, sc_obj["icon"], S_(108), S_(356) + dy_h, alpha=al_h)
                fh = headline_fonts[si]
                tx = S_(162)
                y1 = S_(286) + dy_h
                y2 = y1 + int(round(fh.size * 1.15))
                d.text((tx + S_(3), y1 + S_(4)), sc_obj["line1"], font=fh, fill=(0, 0, 0, int(al_h * 0.82)))
                d.text((tx, y1), sc_obj["line1"], font=fh, fill=(255, 255, 255, al_h))
                d.text((tx + S_(3), y2 + S_(4)), sc_obj["line2"], font=fh, fill=(0, 0, 0, int(al_h * 0.82)))
                d.text((tx, y2), sc_obj["line2"], font=fh, fill=(227, 244, 36, al_h))

            # 4) Tek Kelime Aktif Sarı (#E3F424) Karaoke Altyazı (y=1131..1270)
            active_ch = None
            for ch in tl["chunks"]:
                if ch["show"] <= tsec < ch["hide"]:
                    active_ch = ch
                    break
            if active_ch is not None:
                e_in = ease_out((tsec - active_ch["show"]) / 0.10)
                e_out = clamp01((active_ch["hide"] - tsec) / 0.12)
                al_c = int(255 * e_in * e_out * ui_mul)
                if al_c > 4:
                    active_k = -1
                    for wi, wd in enumerate(active_ch["words"]):
                        if (wd["s"] - 0.025) <= tsec <= (wd["e"] + 0.045):
                            active_k = wi
                        elif tsec >= wd["s"] and active_k == -1:
                            active_k = wi
                    rows = active_ch["_rows"]
                    row_h = S_(66)
                    y_start = S_(1164) if len(rows) == 1 else S_(1131)
                    w_idx_global = 0
                    for ri, row in enumerate(rows):
                        tot_rw = sum(ww for _, ww in row) + S_(15) * max(0, len(row) - 1)
                        rx = (W - tot_rw) / 2.0
                        ry = y_start + ri * row_h
                        for wd, ww in row:
                            is_now = (w_idx_global == active_k)
                            lift = -S_(2) if is_now else 0
                            col = (227, 244, 36, al_c) if is_now else (255, 255, 255, al_c)
                            d.text((rx + S_(3), ry + lift + S_(4)), wd["w"], font=f_cap, fill=(0, 0, 0, int(al_c * 0.86)))
                            d.text((rx, ry + lift), wd["w"], font=f_cap, fill=col)
                            rx += ww + S_(15)
                            w_idx_global += 1

            # 5) Alt Kaynak + Temsilî Not + BİLGİ DOZU İmzası (kapanış cümlesinde tamamen söner)
            x_n1 = (W - wlen(d, note1_txt, f_note1)) / 2.0
            x_n2 = (W - wlen(d, note2_txt, f_note2)) / 2.0
            d.text((x_n1 + S_(2), S_(1753)), note1_txt, font=f_note1, fill=(0, 0, 0, int(175 * ui_mul)))
            d.text((x_n1, S_(1751)), note1_txt, font=f_note1, fill=(232, 236, 239, int(225 * ui_mul)))
            d.text((x_n2 + S_(2), S_(1786)), note2_txt, font=f_note2, fill=(0, 0, 0, int(155 * ui_mul)))
            d.text((x_n2, S_(1784)), note2_txt, font=f_note2, fill=(167, 176, 184, int(195 * ui_mul)))

            al_br = int(255 * ui_mul)
            xb = (W - brand_tot) / 2.0
            yb = S_(1828)
            d.text((xb + S_(3), yb + S_(4)), "BİLGİ", font=f_brand, fill=(0, 0, 0, int(200 * ui_mul)))
            d.text((xb, yb), "BİLGİ", font=f_brand, fill=(255, 255, 255, al_br))
            d.text((xb + brand_w1 + S_(3), yb + S_(4)), "DOZU", font=f_brand, fill=(0, 0, 0, int(200 * ui_mul)))
            d.text((xb + brand_w1, yb), "DOZU", font=f_brand, fill=(227, 244, 36, al_br))

        # 6) Onaylı Saf 3D Kapanış Ekranı (SADECE animasyon, sıfır yazı/çubuk kalabalığı!)
        endcard_v2.composite_endcard(ov, tsec, cta_start, click_delay=cta_click_delay, W=W, H=H)

        frame_rgb = Image.alpha_composite(bg.convert("RGBA"), ov).convert("RGB")
        try:
            proc.stdin.write(frame_rgb.tobytes())
        except BrokenPipeError:
            print(f"[render] {vdir_arg}: ffmpeg erken kapandı ({fi}/{NF})", flush=True)
            break
        if fi % 300 == 0:
            print(f"{vdir_arg} frame {fi}/{NF}", flush=True)

    try:
        proc.stdin.close()
    except Exception:
        pass
    rc = proc.wait()
    plates_by_idx.clear()
    gc.collect()
    if rc != 0:
        raise RuntimeError(f"ffmpeg render hata kodu: {rc}")
    print(f"done: {out_mp4} ({os.path.getsize(out_mp4) / 1e6:.2f} MB)")


# ---------------------------------------------------------------- AŞAMA 5: COVER (1080x1920 Shorts Kapak Üretici)
def stage_cover(vdir_arg: str, explicit_cfg_path: str = None):
    """Onaylı Bilgi Dozu Shorts kapak görselini (<work_dir>/kapak.jpg, 1080x1920) üretir."""
    work_dir, cfg, _ = _resolve_context(vdir_arg, explicit_cfg_path)
    scenes = _discover_scenes(work_dir, cfg)
    src = Image.open(os.path.join(work_dir, scenes[0])).convert("RGB")
    CW_K, CH_K = 1080, 1920
    sc = max(CW_K / src.width, CH_K / src.height)
    nw, nh = int(src.width * sc + 0.5), int(src.height * sc + 0.5)
    im = src.resize((nw, nh), Image.LANCZOS).crop(((nw - CW_K) // 2, (nh - CH_K) // 2, (nw - CW_K) // 2 + CW_K, (nh - CH_K) // 2 + CH_K))
    im = ImageEnhance.Contrast(ImageEnhance.Color(im).enhance(1.12)).enhance(1.10)

    arr = np.asarray(im).astype(np.float32) / 255.0
    # Alt %55 okuma karartması + üst hafif vinyet
    top_g = (np.linspace(1.0, 0.0, 380, dtype=np.float32) ** 1.6) * 0.48
    arr[:380] *= (1.0 - top_g[:, None, None])
    bot_g = (np.linspace(0.0, 1.0, 980, dtype=np.float32) ** 1.35) * 0.88
    arr[CH_K - 980:] *= (1.0 - bot_g[:, None, None])
    canvas = Image.fromarray(np.clip(arr * 255.0, 0, 255).astype(np.uint8)).convert("RGBA")
    d = ImageDraw.Draw(canvas)

    # Üst ortalı 3D BİLGİ DOZU rozeti
    f_pill = load_font("Poppins-Bold.ttf", 34)
    ptxt = "BİLGİ DOZU"
    pbb = d.textbbox((0, 0), ptxt, font=f_pill)
    pw = (pbb[2] - pbb[0]) + 64
    ph = 64
    px0, py0 = (CW_K - pw) // 2, 118
    d.rounded_rectangle([px0, py0 + 5, px0 + pw, py0 + ph + 5], radius=18, fill=BADGE_BEVEL)
    d.rounded_rectangle([px0, py0, px0 + pw, py0 + ph], radius=18, fill=BRAND_YEL)
    d.text((px0 + 32 - pbb[0], py0 + (ph - (pbb[3] - pbb[1])) / 2 - pbb[1] - 1), ptxt, font=f_pill, fill=DARK_TEXT)

    # 2 satır dev kapak başlığı
    raw_lines = _flatten_title_lines(cfg.get("cover_lines") or cfg.get("title") or cfg.get("title_lines"))
    if len(raw_lines) >= 2:
        l1, l2 = raw_lines[0], raw_lines[1]
    elif raw_lines:
        l1, l2 = _wrap_two_lines_20(raw_lines[0], 18)
    else:
        l1, l2 = ("BİLİMSEL", "GERÇEK!")

    sz = 118
    while sz > 64:
        f_cov = load_font("Anton-Regular.ttf", sz)
        if max(wlen(d, l1, f_cov), wlen(d, l2, f_cov)) <= CW_K - 110:
            break
        sz -= 4
    f_cov = load_font("Anton-Regular.ttf", sz)

    y_base = 1320
    for idx_l, (line_txt, fill_c) in enumerate([(l1, PURE_WHITE), (l2, BRAND_YEL)]):
        bb = d.textbbox((0, 0), line_txt, font=f_cov)
        lx = (CW_K - (bb[2] - bb[0])) / 2.0 - bb[0]
        ly = y_base + idx_l * int(sz * 1.16)
        d.text((lx + 5, ly + 7), line_txt, font=f_cov, fill=(0, 0, 0, 220))
        d.text((lx, ly), line_txt, font=f_cov, fill=fill_c, stroke_width=4, stroke_fill=(0, 0, 0, 235))

    out_cov = os.path.join(work_dir, "kapak.jpg")
    canvas.convert("RGB").save(out_cov, quality=93)
    print(f"cover: {out_cov}")
    return out_cov


# ---------------------------------------------------------------- CLI Giriş Noktası
def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    stage = sys.argv[1]
    vdir_arg = sys.argv[2]
    explicit_cfg = sys.argv[3] if len(sys.argv) > 3 else None

    if stage == "plates":
        stage_plates(vdir_arg, explicit_cfg)
    elif stage == "timing":
        stage_timing(vdir_arg, explicit_cfg)
    elif stage == "music":
        stage_music(vdir_arg, explicit_cfg)
    elif stage == "render":
        render_video(vdir_arg, explicit_cfg)
    elif stage == "cover":
        stage_cover(vdir_arg, explicit_cfg)
    elif stage == "publish":
        import publish
        publish.main([vdir_arg] + sys.argv[3:])
    elif stage == "all":
        stage_plates(vdir_arg, explicit_cfg)
        stage_timing(vdir_arg, explicit_cfg)
        stage_music(vdir_arg, explicit_cfg)
        render_video(vdir_arg, explicit_cfg)
        stage_cover(vdir_arg, explicit_cfg)
    else:
        raise ValueError(f"Bilinmeyen aşama: {stage}")


if __name__ == "__main__":
    main()
