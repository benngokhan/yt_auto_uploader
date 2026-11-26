#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BİLGİ DOZU — ONAYLI MASTER v2.2 SHORTS RENDER MOTORU (sablon_v2 / video_196 Birebir Kilitli)

Onaylı koordinat ve ses mimarisi (1080x1920 @ 30fps):
  - Üst İlerleme Çubuğu: x=78..1038 (960x8 px), y=48..56, zemin #3A3A3A, dolgu #E3F424
  - Sol Üst 3D Rozet: x=77, y=210 (214x58 px, 3x supersampled ArchivoBlack "BİLGİ DOZU")
  - Ortalanmış 2 Satır Sahne Başlığı: cx=540, y1=287, y2=363, Poppins-Bold 64 px, <=20 harf/satır,
    TAM BÜYÜK HARF; 1. satır solunda satır içi semantik sarı vektör rozet (?, ! daire içinde;
    ⚡, ▼, ▲, ✔ koyu konturlu vektör), 1. satır #FFFFFF beyaz, 2. satır #E3F424 limon sarısı
  - Ortalanmış 2 Satır Tek-Kelime Karaoke Altyazı: cx=540, y1=1131, y2=1205, Poppins-Bold 50 px,
    girişte %100 beyaz, YALNIZCA o an okunan tek kelime #E3F424 sarı
  - Alt Kaynak & Marka İmzası: y=1751 görsel notu, y=1790 konuya özel bilimsel kaynak (Poppins-Regular 27 px),
    y=1840 ArchivoBlack 46 px "BİLGİ DOZU" ("BİLGİ " #FFFFFF + "DOZU" #E3F424)
  - Saf 3D Kapanış Ekranı (endcard_v2.py): "Daha fazla Bilgi Dozu..." başladığı an arayüz söner,
    arka plan bulanıklaşıp kararır ve tam "takip et!" dendiğinde fare tıklar
  - Broadcast Jenerik Ses Mimarisi: 116 BPM Dm9 belgesel merak jeneriği, 1.45s tam ses intro,
    ~0.62s cümle arası nefes esleri, konuşmada 50ms look-ahead -15.6 dB auto-ducking + 850 Hz FIR LPF,
    sabit lineer -14.2 LUFS kalibrasyon

Kullanım:
  python3 shorts_pipeline.py <plates|timing|music|render|cover|all> <video_id> [config_path]
"""

from __future__ import annotations

import contextlib
import difflib
import gc
import json
import math
import os
import re
import shutil
import subprocess
import sys
import unicodedata
import urllib.parse
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

try:
    from .subtitle_utils import SubtitleFitError, clean_subtitle_block
except ImportError:
    from subtitle_utils import SubtitleFitError, clean_subtitle_block

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import endcard_v2  # noqa: E402
from shorts_acceptance import (  # noqa: E402
    EXPECTED_SCENES,
    MIN_SCENE_SECONDS,
    MAX_SCENE_SECONDS,
    ShortsAcceptanceError,
    sha256_file,
    validate_duration,
    validate_render_manifest_v2,
    validate_scene_intervals,
    validate_v2_production_context,
)


def _resolve_ffmpeg() -> str:
    envn = os.environ.get("MIRA_MOTOR_FFMPEG")
    if envn and os.path.exists(envn):
        return envn
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

W = int(os.environ.get("MIRA_MOTOR_W", "1080"))
H = int(os.environ.get("MIRA_MOTOR_H", "1920"))
FPS = int(os.environ.get("MIRA_MOTOR_FPS", "30"))
SR = 44100
S_SCALE = W / 1080.0


def S_(px: float) -> int:
    return max(1, int(round(px * S_SCALE)))


# Onaylı sablon_v2 (video_187..196) Birebir Renk Paleti
LEMON = (227, 244, 36, 255)       # #E3F424 ana vurgu, ilerleme dolgusu, 2. satır başlık & aktif kelime
ICON_YEL = (255, 220, 32, 255)    # #FFDC20 semantik ikon rozeti altın sarısı
WHITE = (255, 255, 255, 255)      # #FFFFFF 1. satır başlık & pasif altyazı
SEC_TXT = (236, 236, 239, 248)    # #ECECEF alt kaynak ve görsel bilgi satırları
BTN_TXT = (36, 40, 28, 255)       # 3D limon rozet koyu metin rengi
BRAND_YEL = LEMON
BADGE_BEVEL = (142, 156, 16, 255)
DARK_TEXT = BTN_TXT
PURE_WHITE = WHITE

def _miks_ayarlari() -> dict:
    """Ses miks ayarları: motor/ayarlar.json -> "miks". Dosya/bölüm yoksa onaylı değerler kullanılır."""
    try:
        with open(os.path.join(HERE, "ayarlar.json"), encoding="utf-8") as _f:
            _m = json.load(_f).get("miks")
        return _m if isinstance(_m, dict) else {}
    except Exception:
        return {}


_MIKS = _miks_ayarlari()

DEFAULT_INTRO_LEAD = 1.45
DEFAULT_SENT_PAUSE = float(_MIKS.get("cumle_arasi_es_sn", 0.54))          # cümle arası es süresi
DEFAULT_OUTRO_HOLD = endcard_v2.OUTRO_HOLD_SEC
DUCK_FLOOR = float(_MIKS.get("muzik_kisma_tabani", 0.135))                # konuşma sırasında müzik seviyesi (1.0 = tam)
TARGET_LUFS = float(_MIKS.get("hedef_ses_yuksekligi_lufs", -14.2))        # son miks ses yüksekliği hedefi


# ---------------------------------------------------------------- Türkçe & Font Yardımcıları
def N_(s: str) -> str:
    return unicodedata.normalize("NFC", str(s or ""))


def tr_upper(s: str) -> str:
    temiz = "".join(
        ch if (unicodedata.category(ch).startswith(("L", "N")) or ch in " .,!?:;'%+-/()•") else " "
        for ch in N_(s)
    )
    return re.sub(r"\s+", " ", temiz).strip().replace("i", "İ").replace("ı", "I").upper()


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
    "Poppins-Bold.ttf": ["Poppins-Bold.ttf", "ArchivoBlack-Regular.ttf"],
    "Poppins-SemiBold.ttf": ["Poppins-SemiBold.ttf", "Poppins-Bold.ttf"],
    "Poppins-Medium.ttf": ["Poppins-Medium.ttf", "Poppins-Regular.ttf"],
    "Poppins-Regular.ttf": ["Poppins-Regular.ttf", "Poppins-Medium.ttf"],
    "ArchivoBlack-Regular.ttf": ["ArchivoBlack-Regular.ttf", "Anton-Regular.ttf", "Poppins-Bold.ttf"],
    "Anton-Regular.ttf": ["Anton-Regular.ttf", "ArchivoBlack-Regular.ttf", "Poppins-Bold.ttf"],
}

_FONT_CACHE: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def load_font(name: str, size: int) -> ImageFont.FreeTypeFont:
    size = max(8, int(size))
    key = (name, size)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    candidates = FONT_FALLBACKS.get(name, [name, "Poppins-Bold.ttf"])
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
    return 0.0 if v <= 0.0 else (1.0 if v >= 1.0 else float(v))


def ease_out_cubic(x: float) -> float:
    x = clamp01(x)
    return 1.0 - (1.0 - x) ** 3


def ease_io(t: float) -> float:
    x = clamp01(t)
    return x * x * (3.0 - 2.0 * x)


# ---------------------------------------------------------------- Konfigürasyon & Klasör Çözücü
def _resolve_context(vdir_arg: str, explicit_cfg_path: str | None = None):
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
            with open(cp, encoding="utf-8") as fh:
                conf_all = json.load(fh)
            cfg_path_used = cp
            break

    base = os.path.basename(work_dir.rstrip("/"))
    cfg = None
    for k in (vdir_arg, base, f"shorts/{base}"):
        if k in conf_all:
            cfg = conf_all[k]
            break
    if cfg is None:
        local_cfg = os.path.join(work_dir, "config.json")
        if os.path.exists(local_cfg):
            with open(local_cfg, encoding="utf-8") as fh:
                cfg = json.load(fh)
        else:
            raise KeyError(f"'{vdir_arg}' için shorts_config.json kaydı bulunamadı ({cfg_path_used})")
    return work_dir, cfg, cfg_path_used


# ---------------------------------------------------------------- Başlık & Semantik İkon Çözümleyici
STOPWORDS_TR = {
    "bir", "bu", "şu", "o", "ve", "ile", "için", "gibi", "kadar", "daha",
    "çok", "en", "her", "hiç", "ama", "fakat", "ancak", "yani", "işte",
    "aslında", "tam", "ise", "de", "da", "ki", "mi", "mı", "mu", "mü",
    "olarak", "olan", "olur", "olduğu", "sonra", "önce", "üzere", "göre",
    "nedeniyle", "sayesinde", "tarafından", "böylece", "üzerinde", "altında",
    "içinde", "arasında", "doğru", "karşı", "bile", "sadece", "yalnızca",
    "peki", "acaba", "neden", "nasıl", "ne",
}


def _flatten_title_lines(raw_title) -> list[str]:
    if not raw_title:
        return []
    lines = []
    for item in raw_title:
        if isinstance(item, str):
            s = item.strip()
        elif isinstance(item, (list, tuple)):
            parts = []
            for sub in item:
                if isinstance(sub, str) and sub not in ("g", "w", "y", ""):
                    parts.append(sub)
                elif isinstance(sub, (list, tuple)) and len(sub) >= 1 and isinstance(sub[0], str):
                    parts.append(sub[0])
            s = " ".join(p.strip() for p in parts if p.strip())
        else:
            s = str(item).strip()
        if s:
            lines.append(tr_upper(s))
    return lines


def _wrap_two_lines_20(text_upper: str, max_chars: int = 20) -> tuple[str, str]:
    """Metni kelime ortasından bölmeden <=20 karakterlik 2 dengeli satıra ayırır."""
    words = [w for w in tr_upper(text_upper).split() if w]
    if not words:
        return ("BİLGİ DOZU", "BİLİMSEL GERÇEK")
    if len(words) == 1:
        return (words[0][:max_chars], "GERÇEĞİ")

    best_pair = (words[0][:max_chars], " ".join(words[1:])[:max_chars])
    best_score = 1e9
    for split_idx in range(1, len(words)):
        l1 = " ".join(words[:split_idx])
        l2 = " ".join(words[split_idx:])
        over1 = max(0, len(l1) - max_chars) * 14
        over2 = max(0, len(l2) - max_chars) * 14
        score = over1 + over2 + abs(len(l1) - len(l2))
        if score < best_score:
            best_score = score
            best_pair = (l1, l2)

    l1, l2 = best_pair
    while len(l1) > max_chars and " " in l1:
        l1 = l1.rsplit(" ", 1)[0]
    while len(l2) > max_chars and " " in l2:
        l2 = l2.rsplit(" ", 1)[0]
    return (l1[:max_chars].strip() or "BİLİMSEL", l2[:max_chars].strip() or "GERÇEK!")


def _sanitize_headline_pair(l1: str, l2: str, max_chars: int = 20) -> tuple[str, str]:
    s1 = " ".join(tr_upper(l1).split())
    s2 = " ".join(tr_upper(l2).split())
    if not s1 or not s2:
        return _wrap_two_lines_20(f"{s1} {s2}", max_chars=max_chars)
    if len(s1) <= max_chars and len(s2) <= max_chars:
        return (s1, s2)
    return _wrap_two_lines_20(f"{s1} {s2}", max_chars=max_chars)


def _classify_semantic_icon(sent: str, idx: int, total_scenes: int) -> str:
    low = tr_lower(sent)
    if "?" in sent or idx == total_scenes - 1 or any(q in low for q in ("hiç merak", "bilir misin", "fark ettin mi", "neden ", "nasıl ")):
        return "?"
    if any(k in low for k in ("değil", "yoktur", "yok ", "yanlış", "efsane", "sanılanın", "aksine", "asla ", "düşer", "azalır", "kaybolur")):
        return "▼"
    if any(k in low for k in ("tepkime", "elektrik", "enerji", "beyin", "sinir", "nöron", "hız", "saniye", "deney", "ışık", "foton", "lazer", "şok", "dalga")):
        return "⚡"
    if any(k in low for k in ("kat ", "katı", "yüzde", "milyon", "milyar", "derece", "kilometre", "metre", "ton ", "artar", "yükselir", "büyür", "rekor")):
        return "▲"
    if any(k in low for k in ("sayesinde", "korur", "engeller", "keser", "çözüm", "kanıt", "sağlar", "kurtarır", "başarır")):
        return "✔"
    return "!"


def _distill_headline_from_sentence(sent: str, fallback_label: str = "") -> tuple[str, str]:
    src = fallback_label.strip() if fallback_label and len(fallback_label.strip()) >= 8 else sent
    clean = re.sub(r"[,:;\"'()\[\]—–-]", " ", src)
    clean = re.sub(r"[.!?]+$", "", clean).strip()
    tokens = clean.split()
    filtered = []
    for t in tokens:
        tl = norm_word(t)
        if tl in ("yorumlara", "yaz", "yazın", "takip", "abone", "unutma", "daha", "fazla"):
            break
        filtered.append(t)
    if len(filtered) >= 2:
        tokens = filtered

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


def resolve_scene_headlines(cfg: dict, sents: list[str], n_scenes: int) -> list[dict]:
    """Her sahne için onaylı `(icon, line1, line2)` sözlüğü döndürür (<=20 karakter/satır)."""
    explicit = cfg.get("scene_headlines")
    out = []
    if explicit and isinstance(explicit, list):
        for i in range(n_scenes):
            item = explicit[min(i, len(explicit) - 1)]
            if isinstance(item, dict):
                ic = str(item.get("icon") or item.get("ikon") or _classify_semantic_icon("", i, n_scenes))
                l1 = str(item.get("line1") or item.get("satir1") or "")
                l2 = str(item.get("line2") or item.get("satir2") or "")
                l1, l2 = _sanitize_headline_pair(l1, l2, 20)
            elif isinstance(item, (list, tuple)) and len(item) >= 3:
                ic = str(item[0])
                l1, l2 = _sanitize_headline_pair(str(item[1]), str(item[2]), 20)
            elif isinstance(item, (list, tuple)) and len(item) == 2:
                ic = _classify_semantic_icon(" ".join(str(x) for x in item), i, n_scenes)
                l1, l2 = _sanitize_headline_pair(str(item[0]), str(item[1]), 20)
            else:
                ic = _classify_semantic_icon(str(item), i, n_scenes)
                l1, l2 = _wrap_two_lines_20(str(item), 20)
            if ic not in ("?", "▼", "⚡", "▲", "!", "✔"):
                ic = "?" if ("?" in l1 or "?" in l2 or i in (0, n_scenes - 1)) else "!"
            out.append({"icon": ic, "line1": l1, "line2": l2})
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


# ---------------------------------------------------------------- sablon_v2 Birebir Görsel Bileşenler
def render_3d_lime_pill(
    label: str,
    bw_px: int,
    bh_px: int,
    radius_px: int,
    font_px: int,
    scale: float = 1.0,
    alpha: float = 1.0,
    press: float = 0.0,
    sheen_prog: float = -1.0,
    ripple_prog: float = -1.0,
) -> Image.Image:
    """sablon_v2/build_v2_shorts.py birebir 3x supersampled 3D limon rozeti."""
    SS = 3
    bw, bh, r = bw_px * SS, bh_px * SS, radius_px * SS
    pad = 40 * SS
    cw, ch = bw + 2 * pad, bh + 2 * pad
    im = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))

    lip_full = max(4, int(round(bh_px * 0.085))) * SS
    press_dy = int(round(lip_full * 0.72 * clamp01(press)))
    lip_vis = max(1 * SS, lip_full - press_dy)

    x0 = pad
    y0 = pad + press_dy

    if 0.0 <= ripple_prog <= 1.0:
        rp = ease_out_cubic(ripple_prog)
        grow = int(round(26 * SS * rp))
        r_alpha = int(round(150 * (1.0 - rp) ** 1.6))
        if r_alpha > 2:
            ImageDraw.Draw(im).rounded_rectangle(
                [x0 - grow, pad - grow, x0 + bw + grow, pad + bh + lip_full + grow],
                radius=r + grow,
                outline=(227, 244, 36, r_alpha),
                width=max(2, int(3.5 * SS * (1.0 - 0.4 * rp))),
            )

    shd = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    ds = ImageDraw.Draw(shd)
    ds.rounded_rectangle(
        [x0 - 2 * SS, pad + lip_full + 3 * SS, x0 + bw + 2 * SS, pad + bh + lip_full + 9 * SS],
        radius=r,
        fill=(0, 0, 0, 195),
    )
    im = Image.alpha_composite(im, shd.filter(ImageFilter.GaussianBlur(radius=6 * SS)))

    d = ImageDraw.Draw(im)
    d.rounded_rectangle([x0, y0 + lip_vis, x0 + bw, y0 + bh + lip_vis], radius=r, fill=(142, 156, 16, 255))
    d.rounded_rectangle([x0, y0, x0 + bw, y0 + bh], radius=r, fill=(242, 252, 76, 255))
    inset = max(2, 2 * SS)
    d.rounded_rectangle([x0 + inset, y0 + inset, x0 + bw - inset, y0 + bh - inset], radius=max(2, r - inset), fill=(212, 227, 36, 255))

    if 0.0 <= sheen_prog <= 1.0:
        mask = Image.new("L", (cw, ch), 0)
        ImageDraw.Draw(mask).rounded_rectangle([x0, y0, x0 + bw, y0 + bh], radius=r, fill=255)
        sheen = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        sd = ImageDraw.Draw(sheen)
        cx_s = (x0 - bw * 0.35) + (bw * 1.70) * sheen_prog
        band_w = bw * 0.20
        poly = [
            (cx_s - band_w + 18 * SS, y0 - 4 * SS),
            (cx_s + band_w + 18 * SS, y0 - 4 * SS),
            (cx_s + band_w - 18 * SS, y0 + bh + 4 * SS),
            (cx_s - band_w - 18 * SS, y0 + bh + 4 * SS),
        ]
        sd.polygon(poly, fill=(255, 255, 235, 95))
        sheen = sheen.filter(ImageFilter.GaussianBlur(radius=4 * SS))
        sheen.putalpha(ImageChops.multiply(sheen.getchannel("A"), mask))
        im = Image.alpha_composite(im, sheen)

    f_b = load_font("ArchivoBlack-Regular.ttf", font_px * SS)
    txt = N_(label)
    t_tmp = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    td = ImageDraw.Draw(t_tmp)
    bb = td.textbbox((0, 0), txt, font=f_b)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    td.text(((bw - tw) / 2 - bb[0], (bh - th) / 2 - bb[1]), txt, font=f_b, fill=BTN_TXT)
    wide_w = int(round(bw * 1.04))
    t_wide = t_tmp.resize((wide_w, bh), Image.Resampling.LANCZOS)
    im.alpha_composite(t_wide, (int(round(x0 - (wide_w - bw) / 2)), y0))

    out_w, out_h = bw_px + 80, bh_px + 80
    base = im.resize((out_w, out_h), Image.Resampling.LANCZOS)
    if abs(scale - 1.0) > 1e-3:
        base = base.resize((max(4, int(round(base.width * scale))), max(4, int(round(base.height * scale)))), Image.Resampling.LANCZOS)
    if alpha < 0.999:
        r_c, g_c, b_c, a_c = base.split()
        base = Image.merge("RGBA", (r_c, g_c, b_c, a_c.point(lambda p: int(p * alpha))))
    return base


def _verified_source_url_format(value: str) -> str:
    """Son çizim kapısı: yalnız HTTPS ve bilinen bilimsel/kurumsal alan adları."""
    raw = str(value or "").strip()
    try:
        parsed = urllib.parse.urlparse(raw)
        host = (parsed.hostname or "").lower().rstrip(".")
    except Exception:
        return ""
    allowed = ("nasa.gov", "boeing.com", "doi.org", "pubmed.ncbi.nlm.nih.gov", "ncbi.nlm.nih.gov",
               "nature.com", "science.org", "aaas.org", "nejm.org", "thelancet.com", "pnas.org",
               "aps.org", "arxiv.org", "who.int", "cdc.gov", "nih.gov", "esa.int")
    if parsed.scheme != "https" or not any(host == d or host.endswith("." + d) for d in allowed):
        return ""
    return raw


def build_static_overlay(
    note1_txt: str = "",
    note2_txt: str = "",
) -> Image.Image:
    """sablon_v2/build_v2_shorts.py birebir statik arayüz katmanı:
    - y=48..56, x=78..1038 üst ilerleme çubuğu zemini (#3A3A3A)
    - x=77, y=210 sol üst 3D BİLGİ DOZU rozeti
    - y=1751 görsel notu, y=1790 bilimsel kaynak (Poppins-Regular 27 px)
    - y=1840 ArchivoBlack 46 px BİLGİ DOZU imzası"""
    SS = 2
    ov = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)

    # 1. Üst ilerleme çubuğu zemini: x=78..1038 (960 px), y=48..56 (8 px), #3A3A3A
    d.rounded_rectangle([S_(78) * SS, S_(48) * SS, S_(1038) * SS - 1, S_(56) * SS - 1], radius=S_(4) * SS, fill=(58, 58, 58, 235))

    # 2. Alt kaynak & görsel notu: y=1751 (görsel notu) & y=1790 (Kaynak: ...)
    # Boş satır çizilmez: gerçek kaynak yoksa kaynak satırı GÖSTERİLMEZ, görsel notu alt satıra iner.
    s1 = N_(note2_txt or "")
    s2 = N_(note1_txt or "")
    satirlar = [t for t in (s1, s2) if t.strip()]
    y_ler = (S_(1751), S_(1790)) if len(satirlar) == 2 else (S_(1790),)
    for y_line, stxt in zip(y_ler, satirlar):
        sz_ss = S_(27) * SS
        f_src_ss = load_font("Poppins-Regular.ttf", sz_ss)
        while (d.textbbox((0, 0), stxt, font=f_src_ss)[2] - d.textbbox((0, 0), stxt, font=f_src_ss)[0]) > (W - S_(84)) * SS and sz_ss > S_(12) * SS:
            sz_ss -= 2
            f_src_ss = load_font("Poppins-Regular.ttf", sz_ss)
        sbb = d.textbbox((0, 0), stxt, font=f_src_ss)
        sw = sbb[2] - sbb[0]
        sx = (W * SS - sw) / 2 - sbb[0]
        sy = y_line * SS - sbb[1]
        d.text((sx + 2 * SS, sy + 3 * SS), stxt, font=f_src_ss, fill=(0, 0, 0, 205))
        d.text((sx, sy), stxt, font=f_src_ss, fill=SEC_TXT)

    # 3. Alt marka imzası: ArchivoBlack 46 px "BİLGİ " (#FFFFFF) + "DOZU" (#E3F424) @ y=1840
    f_sign_ss = load_font("ArchivoBlack-Regular.ttf", S_(46) * SS)
    t_b, t_d = N_("BİLGİ "), N_("DOZU")
    bb_full = d.textbbox((0, 0), t_b + t_d, font=f_sign_ss)
    bb_b = d.textbbox((0, 0), t_b, font=f_sign_ss)
    bb_d = d.textbbox((0, 0), t_d, font=f_sign_ss)
    full_w = bb_full[2] - bb_full[0]
    sx0 = (W * SS - full_w) / 2
    y_top = S_(1840) * SS
    w_b_adv = d.textlength(t_b, font=f_sign_ss)

    d.text((sx0 - bb_b[0] + 3 * SS, y_top - bb_full[1] + 4 * SS), t_b, font=f_sign_ss, fill=(0, 0, 0, 215))
    d.text((sx0 + w_b_adv - bb_d[0] + 3 * SS, y_top - bb_full[1] + 4 * SS), t_d, font=f_sign_ss, fill=(0, 0, 0, 215))
    d.text((sx0 - bb_b[0], y_top - bb_full[1]), t_b, font=f_sign_ss, fill=WHITE)
    d.text((sx0 + w_b_adv - bb_d[0], y_top - bb_full[1]), t_d, font=f_sign_ss, fill=LEMON)

    base = ov.resize((W, H), Image.Resampling.LANCZOS)

    # 4. Sol üst 3D kabartmalı BİLGİ DOZU rozeti @ (77, 210) — TikTok ust arayuzunun altinda
    badge = render_3d_lime_pill("BİLGİ DOZU", bw_px=S_(214), bh_px=S_(53), radius_px=S_(15), font_px=S_(23))
    base.alpha_composite(badge, (S_(77) - 40, S_(210) - 40))
    return base


def draw_semantic_icon(icon_type: str, size_px: int = 44) -> tuple[Image.Image, Image.Image]:
    """sablon_v2/build_v2_shorts.py birebir 4x supersampled semantik sarı vektör ikon:
      - '?' ve '!': Koyu konturlu dolu sarı (#FFDC20) daire içinde ArchivoBlack koyu sembol
      - '⚡', '▼', '▲', '✔': Koyu konturlu geometrik sarı vektör poligon"""
    SS = 4
    S = size_px * SS
    fg = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    sh = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    df = ImageDraw.Draw(fg)
    ds = ImageDraw.Draw(sh)

    sh_col = (0, 0, 0, 215)
    st_col = (10, 12, 16, 225)
    s_off = 4 * SS

    if icon_type == "⚡":
        pts = [
            (S * 0.58, S * 0.04),
            (S * 0.18, S * 0.54),
            (S * 0.46, S * 0.54),
            (S * 0.36, S * 0.96),
            (S * 0.82, S * 0.43),
            (S * 0.53, S * 0.43),
        ]
        ds.polygon([(x, y + s_off) for x, y in pts], fill=sh_col)
        for ox, oy in [(-5, 0), (5, 0), (0, -5), (0, 5), (-4, -4), (4, -4), (-4, 4), (4, 4)]:
            df.polygon([(x + ox, y + oy) for x, y in pts], fill=st_col)
        df.polygon(pts, fill=ICON_YEL)

    elif icon_type == "▼":
        pts = [(S * 0.10, S * 0.20), (S * 0.90, S * 0.20), (S * 0.50, S * 0.86)]
        ds.polygon([(x, y + s_off) for x, y in pts], fill=sh_col)
        for ox, oy in [(-6, 0), (6, 0), (0, -6), (0, 6), (-4, -4), (4, -4), (-4, 4), (4, 4)]:
            df.polygon([(x + ox, y + oy) for x, y in pts], fill=st_col)
        df.polygon(pts, fill=ICON_YEL)

    elif icon_type == "▲":
        pts = [(S * 0.50, S * 0.14), (S * 0.90, S * 0.82), (S * 0.10, S * 0.82)]
        ds.polygon([(x, y + s_off) for x, y in pts], fill=sh_col)
        for ox, oy in [(-6, 0), (6, 0), (0, -6), (0, 6), (-4, -4), (4, -4), (-4, 4), (4, 4)]:
            df.polygon([(x + ox, y + oy) for x, y in pts], fill=st_col)
        df.polygon(pts, fill=ICON_YEL)

    elif icon_type == "✔":
        pts = [
            (S * 0.08, S * 0.54),
            (S * 0.22, S * 0.39),
            (S * 0.40, S * 0.58),
            (S * 0.78, S * 0.16),
            (S * 0.93, S * 0.31),
            (S * 0.40, S * 0.87),
        ]
        ds.polygon([(x, y + s_off) for x, y in pts], fill=sh_col)
        for ox, oy in [(-6, 0), (6, 0), (0, -6), (0, 6), (-4, -4), (4, -4), (-4, 4), (4, 4)]:
            df.polygon([(x + ox, y + oy) for x, y in pts], fill=st_col)
        df.polygon(pts, fill=ICON_YEL)

    else:
        sym = icon_type if icon_type in ("?", "!") else "!"
        pad_c = int(S * 0.07)
        ds.ellipse([pad_c, pad_c + s_off, S - pad_c, S - pad_c + s_off], fill=sh_col)
        df.ellipse([pad_c - 5, pad_c - 5, S - pad_c + 5, S - pad_c + 5], fill=st_col)
        df.ellipse([pad_c, pad_c, S - pad_c, S - pad_c], fill=ICON_YEL)
        f_sym = load_font("ArchivoBlack-Regular.ttf", int(size_px * 0.64 * SS))
        bb = df.textbbox((0, 0), sym, font=f_sym)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
        df.text(((S - tw) / 2 - bb[0], (S - th) / 2 - bb[1]), sym, font=f_sym, fill=(14, 16, 20, 255))

    return (
        fg.resize((size_px * 2, size_px * 2), Image.Resampling.LANCZOS),
        sh.resize((size_px * 2, size_px * 2), Image.Resampling.LANCZOS),
    )


def render_headline_card(icon_type: str, line1: str, line2: str) -> Image.Image:
    """sablon_v2/build_v2_shorts.py birebir ortalanmış 2 satır başlık kartı (y_off=268 -> y1=287, y2=363):
      - 1. satır (#FFFFFF beyaz) + solunda satır içi semantik sarı rozet (?, ▼, ⚡, ▲, !, ✔), cx=540 etrafında ortalı
      - 2. satır (#E3F424 limon sarısı), cx=540 etrafında ortalı
      - Poppins-Bold 64 px + kalın koyu dış kontur + yumuşak GaussianBlur gölge"""
    l1, l2 = _sanitize_headline_pair(line1, line2, max_chars=20)

    SS = 2
    CARD_H = S_(210)
    Y_OFF = S_(268)
    im_txt = Image.new("RGBA", (W * SS, CARD_H * SS), (0, 0, 0, 0))
    im_shd = Image.new("RGBA", (W * SS, CARD_H * SS), (0, 0, 0, 0))
    dt = ImageDraw.Draw(im_txt)
    ds = ImageDraw.Draw(im_shd)

    icon_px = S_(44)
    ic_fg, ic_sh = draw_semantic_icon(icon_type, size_px=icon_px)
    icon_w = icon_px * SS
    gap = S_(16) * SS

    font_px = S_(64)
    max_allowed_w = (W - S_(96)) * SS
    while font_px > S_(48):
        f_h = load_font("Poppins-Bold.ttf", font_px * SS)
        bb1_t = dt.textbbox((0, 0), l1, font=f_h)
        bb2_t = dt.textbbox((0, 0), l2, font=f_h)
        if (icon_w + gap + (bb1_t[2] - bb1_t[0])) <= max_allowed_w and (bb2_t[2] - bb2_t[0]) <= max_allowed_w:
            break
        font_px -= 2
    f_h = load_font("Poppins-Bold.ttf", font_px * SS)

    bb1 = dt.textbbox((0, 0), l1, font=f_h)
    w1, h1 = bb1[2] - bb1[0], bb1[3] - bb1[1]
    combo_w = icon_w + gap + w1

    bb2 = dt.textbbox((0, 0), l2, font=f_h)
    w2 = bb2[2] - bb2[0]

    cx = (W // 2) * SS
    x_start1 = int(round(cx - combo_w / 2))
    y1_top = (S_(287) - Y_OFF) * SS
    cy_line1 = int(round(y1_top + h1 / 2))

    iy = int(round(cy_line1 - icon_w / 2))
    im_shd.alpha_composite(ic_sh, (x_start1, iy))
    im_txt.alpha_composite(ic_fg, (x_start1, iy))

    tx1, ty1 = x_start1 + icon_w + gap - bb1[0], y1_top - bb1[1]
    y2_top = (S_(363) - Y_OFF) * SS
    tx2, ty2 = cx - w2 / 2 - bb2[0], y2_top - bb2[1]

    ds.text((tx1, ty1 + 5 * SS), l1, font=f_h, fill=(0, 0, 0, 215), stroke_width=5 * SS, stroke_fill=(0, 0, 0, 215))
    ds.text((tx2, ty2 + 5 * SS), l2, font=f_h, fill=(0, 0, 0, 215), stroke_width=5 * SS, stroke_fill=(0, 0, 0, 215))

    dt.text((tx1, ty1), l1, font=f_h, fill=WHITE, stroke_width=3 * SS, stroke_fill=(8, 10, 14, 225))
    dt.text((tx2, ty2), l2, font=f_h, fill=LEMON, stroke_width=3 * SS, stroke_fill=(8, 10, 14, 225))

    shd_b = im_shd.filter(ImageFilter.GaussianBlur(radius=6 * SS))
    comp = Image.alpha_composite(shd_b, im_txt)
    return comp.resize((W, CARD_H), Image.Resampling.LANCZOS)


def render_subtitle_state(chunk: dict, active_tok_idx: int) -> Image.Image:
    """sablon_v2/build_v2_shorts.py birebir 2 satır tek-kelime karaoke altyazı (y=1131 & y=1205, Poppins-Bold 50 px)."""
    original_toks = list(chunk["tokens"])
    raw_text = " ".join(N_(token["text"]) for token in original_toks)
    f_sub = load_font("Poppins-Bold.ttf", S_(50))
    cleaned_text = clean_subtitle_block(
        raw_text,
        max_lines=2,
        max_chars_per_line=None,
        max_width_px=S_(785),
        measure_text=lambda line: f_sub.getlength(N_(line)),
    )
    cleaned_words = cleaned_text.split()
    removed_prefix = len(original_toks) - len(cleaned_words)
    if removed_prefix < 0 or [norm_word(t["text"]) for t in original_toks[removed_prefix:]] != [
        norm_word(word) for word in cleaned_words
    ]:
        raise SubtitleFitError("Subtitle cleanup changed spoken-word order; render stopped")
    toks = original_toks[removed_prefix:]
    if not toks:
        raise SubtitleFitError("subtitle is empty after scene-label cleanup")
    if active_tok_idx < removed_prefix:
        active_tok_idx = -1
    else:
        active_tok_idx -= removed_prefix

    box_h = S_(185)
    im_txt = Image.new("RGBA", (W, box_h), (0, 0, 0, 0))
    im_shd = Image.new("RGBA", (W, box_h), (0, 0, 0, 0))
    Y_OFF = S_(1115)
    dt = ImageDraw.Draw(im_txt)
    ds = ImageDraw.Draw(im_shd)

    cleaned_lines = cleaned_text.splitlines()
    l1_cnt = len(cleaned_lines[0].split()) if len(cleaned_lines) > 1 else len(toks)
    lines = [toks[:l1_cnt]]
    if toks[l1_cnt:]:
        lines.append(toks[l1_cnt:])
    if len(lines) > 2 or any(not line for line in lines):
        raise SubtitleFitError("subtitle cannot be rendered in two non-empty lines")

    space_w = dt.textlength(" ", font=f_sub)
    ref_top = dt.textbbox((0, 0), "Ay", font=f_sub)[1]

    for li, ltoks in enumerate(lines):
        if not ltoks:
            continue
        full_str = " ".join(t["text"] for t in ltoks)
        bb_full = dt.textbbox((0, 0), full_str, font=f_sub)
        line_w = bb_full[2] - bb_full[0]
        if line_w > S_(785):
            raise SubtitleFitError(f"subtitle line is wider than the visible limit ({line_w}>{S_(785)} px)")
        x_cur = (W / 2.0) - line_w / 2.0
        y_draw = (S_(1131) + li * S_(74) - Y_OFF) - ref_top

        for k, tk_obj in enumerate(ltoks):
            global_k = k if li == 0 else (l1_cnt + k)
            word = N_(tk_obj["text"])
            color = LEMON if (global_k == active_tok_idx) else WHITE
            ds.text((x_cur, y_draw + S_(4)), word, font=f_sub, fill=(0, 0, 0, 205), stroke_width=S_(4), stroke_fill=(0, 0, 0, 205))
            dt.text((x_cur, y_draw), word, font=f_sub, fill=color, stroke_width=S_(2), stroke_fill=(8, 10, 14, 215))
            x_cur += dt.textlength(word, font=f_sub) + space_w

    return Image.alpha_composite(im_shd.filter(ImageFilter.GaussianBlur(radius=5.5 * S_SCALE)), im_txt)


# ---------------------------------------------------------------- AŞAMA 1: PLATES (sablon_v2 prepare_fullscreen_plate)
def prepare_fullscreen_plate(img_path: str | Path, is_closing: bool = False) -> Image.Image:
    """sablon_v2/build_v2_shorts.py birebir tam ekran 1440x2560 plaka:
    doğal renk (1.06) + net kontrast (1.07) + üst %26 ve alt %42 temiz #0A0C10 okuma vinyeti.
    Orta kadraj (%32..%74) %100 parlak, net ve doğal kalır."""
    PW, PH = S_(1440), S_(2560)
    src = Image.open(img_path).convert("RGB")
    img = ImageOps.fit(src, (PW, PH), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))

    if is_closing:
        arr_s7 = np.asarray(img).copy()
        shift = S_(62)
        shifted = np.zeros_like(arr_s7)
        shifted[:-shift] = arr_s7[shift:]
        shifted[-shift:] = np.array([10, 12, 16], dtype=np.uint8)
        img = Image.fromarray(shifted, "RGB")

    img = ImageEnhance.Color(img).enhance(1.06)
    img = ImageEnhance.Contrast(img).enhance(1.07)

    arr = np.asarray(img, dtype=np.float32)
    ov = np.zeros((PH, 1, 1), dtype=np.float32)
    ytop = int(PH * 0.26)
    ov[:ytop, 0, 0] = (np.linspace(1.0, 0.0, ytop, dtype=np.float32) ** 1.50) * 0.82

    ybot_frac = 0.46 if is_closing else 0.42
    ybot = int(PH * ybot_frac)
    bot_curve = (np.linspace(0.0, 1.0, ybot, dtype=np.float32) ** 1.35) * (0.95 if is_closing else 0.91)
    ov[PH - ybot:, 0, 0] = np.maximum(ov[PH - ybot:, 0, 0], bot_curve)

    dark_bg = np.array([10.0, 12.0, 16.0], dtype=np.float32).reshape((1, 1, 3))
    arr = arr * (1.0 - ov) + dark_bg * ov
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")


def sample_fullscreen_kb(plate: Image.Image, progress: float, mode: int) -> Image.Image:
    p = clamp01(progress)
    p_s = p * p * (3.0 - 2.0 * p)
    pw, ph = plate.size
    if mode % 3 == 0:
        z = 1.02 + 0.07 * p_s
        cx, cy = 0.50, 0.49 + 0.015 * p_s
    elif mode % 3 == 1:
        z = 1.09 - 0.06 * p_s
        cx, cy = 0.485 + 0.03 * p_s, 0.50
    else:
        z = 1.02 + 0.05 * p_s
        cx, cy = 0.50, 0.50 - 0.015 * p_s

    cw, ch = pw / z, ph / z
    x0 = min(max(0.0, pw * cx - cw / 2.0), pw - cw)
    y0 = min(max(0.0, ph * cy - ch / 2.0), ph - ch)
    return plate.resize((W, H), Image.Resampling.BILINEAR, box=(x0, y0, x0 + cw, y0 + ch))


def build_plate(src_path: str, out_path: str, dark_bottom_cta: bool = False):
    out_im = prepare_fullscreen_plate(src_path, is_closing=dark_bottom_cta)
    ext = os.path.splitext(out_path)[1].lower()
    if ext in (".jpg", ".jpeg"):
        out_im.save(out_path, quality=94)
    else:
        out_im.save(out_path)


def _discover_scenes(work_dir: str, cfg: dict) -> list[str]:
    names = list(cfg.get("scenes") or [])
    if not names:
        for prefix in ("s", "bg"):
            found = []
            for idx in range(1, 12):
                for ext in (".png", ".jpg", ".jpeg", ".webp"):
                    cand = f"{prefix}{idx}{ext}"
                    if os.path.exists(os.path.join(work_dir, cand)):
                        found.append(cand)
                        break
            if found:
                names = found
                break
    if not names:
        raise FileNotFoundError(f"{work_dir} içinde sahne görseli (s1.jpg / bg1.png) bulunamadı.")
    return names


def stage_plates(vdir_arg: str, explicit_cfg_path: str | None = None):
    work_dir, cfg, _ = _resolve_context(vdir_arg, explicit_cfg_path)
    names = _discover_scenes(work_dir, cfg)
    for i, n in enumerate(names):
        src = os.path.join(work_dir, n)
        out = os.path.join(work_dir, "plate_" + n)
        build_plate(src, out, dark_bottom_cta=(i == len(names) - 1 and len(names) >= 4))
        print("plate:", out)
    cta_plate = os.path.join(work_dir, "plate_closing_cta.jpg")
    build_plate(os.path.join(work_dir, names[-1]), cta_plate, dark_bottom_cta=True)


# ---------------------------------------------------------------- AŞAMA 2: TIMING (Nefes Esli VO + faster-whisper + v2 Karaoke Chunks)
def read_wav_mono(path: str) -> tuple[np.ndarray, int]:
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
    raise FileNotFoundError(f"{work_dir} içinde vo_raw.wav bulunamadı.")


def prepare_voice_wav(
    raw_wav: str,
    output_wav: str,
    speed_factor: float,
    provider: str = "arena.generate_speech",
) -> None:
    """Prepare the declared Arena voice at 1.00x; format conversion never changes tempo."""
    try:
        factor = float(speed_factor)
    except (TypeError, ValueError) as exc:
        raise ShortsAcceptanceError("voice_speed_factor sayı olmalı") from exc
    if not math.isfinite(factor):
        raise ShortsAcceptanceError("voice_speed_factor sonlu olmalı")
    if provider != "arena.generate_speech":
        raise ShortsAcceptanceError(f"Shorts v2 yalnız Arena sesini kabul eder; sağlayıcı: {provider}")
    if abs(factor - 1.0) >= 1e-9:
        raise ShortsAcceptanceError("Arena sesi 1.00x kalmalı; yalnız biçim dönüştürmeye izin var")

    source_ok = False
    try:
        with wave.open(raw_wav, "rb") as wav:
            source_ok = (
                wav.getnchannels() == 1 and wav.getframerate() == SR
                and wav.getsampwidth() == 2 and wav.getnframes() > 0
            )
    except (OSError, wave.Error):
        pass
    if abs(factor - 1.0) < 1e-9 and source_ok:
        if os.path.abspath(raw_wav) != os.path.abspath(output_wav):
            shutil.copyfile(raw_wav, output_wav)
        return

    command = [FF, "-y", "-hide_banner", "-loglevel", "error", "-i", raw_wav]
    command.extend(["-ar", str(SR), "-ac", "1", "-c:a", "pcm_s16le", output_wav])
    try:
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with wave.open(output_wav, "rb") as wav:
            if wav.getnchannels() != 1 or wav.getframerate() != SR or wav.getsampwidth() != 2 or wav.getnframes() <= 0:
                raise ShortsAcceptanceError("Hazırlanan ses WAV biçim denetiminden geçmedi")
    except ShortsAcceptanceError:
        Path(output_wav).unlink(missing_ok=True)
        raise
    except Exception as exc:  # noqa: BLE001
        Path(output_wav).unlink(missing_ok=True)
        raise ShortsAcceptanceError(f"Arena WAV biçim/tempo işlemi başarısız ({type(exc).__name__})") from exc


def ff_silences(path: str, noise_db: float = -35.0, min_dur: float = 0.14):
    r = subprocess.run(
        [FF, "-hide_banner", "-i", path, "-af", f"silencedetect=noise={noise_db}dB:d={min_dur}", "-f", "null", "-"],
        capture_output=True, text=True,
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


def _align_sentences_to_spans(sents: list[str], spans: list[tuple[float, float]]):
    chars = [max(1, len(s)) for s in sents]
    tot_c = sum(chars)
    tot_s = sum(b - a for a, b in spans) or 1.0
    exp = [tot_s * c / tot_c for c in chars]
    m, n = len(spans), len(sents)
    if m < n:
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


def _map_script_to_asr(script_words: list[str], asr_words: list[dict]) -> list[dict]:
    s_norm = [norm_word(w) for w in script_words]
    a_norm = [norm_word(x["w"]) for x in asr_words]
    sm = difflib.SequenceMatcher(None, s_norm, a_norm, autojunk=False)
    mapped: list[dict | None] = [None] * len(script_words)

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
    return [m for m in mapped if m is not None]


def _try_whisper_words(spaced_wav: str, script_words: list[str]) -> list[dict] | None:
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
        preferred = os.environ.get("MIRA_WHISPER_MODEL", "small")
        model = None
        for m_cand in dict.fromkeys([preferred, "base"]):
            try:
                model = WhisperModel(m_cand, device="cpu", compute_type="int8", cpu_threads=4)
                break
            except Exception:
                continue
        if model is None:
            return None
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


def _syllable_weight(word: str) -> float:
    vowels = sum(1 for ch in tr_lower(word) if ch in "aeıioöuüâîû")
    base = max(1.2, vowels * 1.05 + 0.18 * len(norm_word(word)))
    if any(word.endswith(p) for p in (",", ";", ":")):
        base += 0.45
    elif any(word.endswith(p) for p in (".", "!", "?")):
        base += 0.65
    return base


def build_auto_subtitle_chunks(tokens: list[dict]) -> list[dict]:
    """render_batch_187_196.py birebir 2 satır karaoke paketleyici (<=785 px genişlik, noktalama duyarlı)."""
    if not tokens:
        return []
    f_sub = load_font("Poppins-Bold.ttf", S_(50))
    dummy = Image.new("RGBA", (64, 64))
    d = ImageDraw.Draw(dummy)
    MAX_W = S_(785)

    # Son 7 kelime "Daha fazla Bilgi Dozu için takip et!" ise ayrı kapanış bloğu yap
    tail_norms = [norm_word(t["text"]) for t in tokens[-7:]]
    has_std_cta = len(tokens) >= 10 and "daha" in tail_norms[:2] and any(w.startswith("takip") for w in tail_norms)
    body_toks = tokens[:-7] if has_std_cta else tokens
    cta_toks = tokens[-7:] if has_std_cta else []

    chunks: list[dict] = []
    i = 0
    while i < len(body_toks):
        l1: list[dict] = []
        l2: list[dict] = []
        while i < len(body_toks) and len(l1) < 4:
            cand = " ".join([t["text"] for t in l1] + [body_toks[i]["text"]])
            bb = d.textbbox((0, 0), N_(cand), font=f_sub)
            if (bb[2] - bb[0]) <= MAX_W or not l1:
                l1.append(body_toks[i])
                i += 1
                if l1[-1]["text"][-1:] in ".!?":
                    break
            else:
                break

        if l1 and l1[-1]["text"][-1:] not in ".!?":
            while i < len(body_toks) and len(l2) < 4:
                cand = " ".join([t["text"] for t in l2] + [body_toks[i]["text"]])
                bb = d.textbbox((0, 0), N_(cand), font=f_sub)
                if (bb[2] - bb[0]) <= MAX_W:
                    l2.append(body_toks[i])
                    i += 1
                    if l2[-1]["text"][-1:] in ".!?;:":
                        break
                else:
                    break

        sub_toks = l1 + l2
        chunks.append({
            "l1_count": len(l1),
            "tokens": sub_toks,
            "words": [{"w": t["text"], "s": t["start"], "e": t["end"]} for t in sub_toks],
            "start": sub_toks[0]["start"],
            "speak_end": sub_toks[-1]["end"],
            "end": sub_toks[-1]["end"],
            "show": round(max(0.0, sub_toks[0]["start"] - 0.08), 3),
            "hide": round(sub_toks[-1]["end"] + 0.22, 3),
        })

    if cta_toks:
        chunks.append({
            "l1_count": min(5, len(cta_toks)),
            "tokens": cta_toks,
            "words": [{"w": t["text"], "s": t["start"], "e": t["end"]} for t in cta_toks],
            "start": cta_toks[0]["start"],
            "speak_end": cta_toks[-1]["end"],
            "end": round(cta_toks[-1]["end"] + 1.45, 3),
            "show": round(max(0.0, cta_toks[0]["start"] - 0.08), 3),
            "hide": round(cta_toks[-1]["end"] + 1.45, 3),
            "is_cta": True,
        })

    for ci in range(len(chunks) - 1):
        gap = chunks[ci + 1]["start"] - chunks[ci]["end"]
        if 0 < gap < 0.45:
            chunks[ci]["end"] = round(chunks[ci + 1]["start"] - 0.04, 3)
        else:
            chunks[ci]["end"] = round(chunks[ci]["end"] + 0.22, 3)
        chunks[ci]["hide"] = round(min(chunks[ci]["end"], chunks[ci + 1]["show"] - 0.01), 3)
    return chunks


def stage_timing(vdir_arg: str, explicit_cfg_path: str | None = None):
    work_dir, cfg, _ = _resolve_context(vdir_arg, explicit_cfg_path)
    v2_context = validate_v2_production_context(work_dir, cfg)
    script_path = os.path.join(work_dir, "script.txt")
    script = open(script_path, encoding="utf-8").read().strip()
    raw_wav = ensure_vo_raw(work_dir)

    vo_final = os.path.join(work_dir, "vo_final.wav")
    if v2_context is not None:
        prepare_voice_wav(
            raw_wav, vo_final, v2_context["voice_speed_factor"],
            provider=v2_context["voice_provider"],
        )
        x_raw, fr = read_wav_mono(vo_final)
    else:
        if os.path.abspath(raw_wav) != os.path.abspath(vo_final):
            shutil.copyfile(raw_wav, vo_final)
        x_raw, fr = read_wav_mono(raw_wav)
        if fr != SR:
            subprocess.run([FF, "-y", "-hide_banner", "-loglevel", "error",
                            "-i", raw_wav, "-ar", str(SR), "-ac", "1", "-c:a", "pcm_s16le", vo_final], check=True)
            x_raw, fr = read_wav_mono(vo_final)

    dur_raw = len(x_raw) / float(fr)
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", script) if s.strip()]
    if not sents:
        sents = [script]

    intro_lead = float(cfg.get("intro_lead", DEFAULT_INTRO_LEAD))
    pause_target = float(cfg.get("sentence_pause", DEFAULT_SENT_PAUSE))
    outro_hold = float(cfg.get("outro_hold", DEFAULT_OUTRO_HOLD))

    all_script_words = [w for s in sents for w in s.split()]
    raw_whisper = _try_whisper_words(vo_final, all_script_words)

    tokens_flat: list[dict] = []
    spaced_sent_spans: list[tuple[float, float]] = []

    if raw_whisper and len(raw_whisper) == len(all_script_words):
        # render_batch_187_196.py yöntemi: kelimeleri ASLA kesmeden yalnızca cümle sonu doğal sessizlik ortasına nefes ekle
        sent_word_ranges: list[tuple[int, int]] = []
        wc = 0
        for s in sents:
            k = len(s.split())
            sent_word_ranges.append((wc, wc + k - 1))
            wc += k

        pauses: list[tuple[int, float]] = [(0, intro_lead)]
        xf = int(0.006 * fr)
        for si in range(len(sent_word_ranges) - 1):
            _, w_end_idx = sent_word_ranges[si]
            w_nxt_idx, _ = sent_word_ranges[si + 1]
            t_e = float(raw_whisper[w_end_idx]["e"])
            t_n = float(raw_whisper[w_nxt_idx]["s"])
            if t_n > t_e + 0.03:
                i_a = max(0, min(len(x_raw) - 1, int(round(t_e * fr))))
                i_b = max(i_a + 1, min(len(x_raw), int(round(t_n * fr))))
                # Sessizlik aralığındaki en düşük enerjili noktadan böl (sessiz harfleri asla kesmez)
                win_q = max(64, int(0.012 * fr))
                if i_b - i_a > win_q * 2:
                    env_seg = np.convolve(np.abs(x_raw[i_a:i_b]), np.ones(win_q) / win_q, mode="valid")
                    cut_smp = i_a + win_q // 2 + int(np.argmin(env_seg))
                else:
                    cut_smp = (i_a + i_b) // 2
                gap = t_n - t_e
                add_s = max(0.0, min(0.48, pause_target - gap))
                if add_s >= 0.05:
                    pauses.append((cut_smp, round(add_s, 3)))

        pieces: list[np.ndarray] = []
        prev_smp = 0
        for cut_smp, add_s in pauses:
            if cut_smp > prev_smp:
                seg = x_raw[prev_smp:cut_smp].copy()
                if len(seg) > 2 * xf and prev_smp > 0:
                    seg[:xf] *= np.linspace(0.0, 1.0, xf)
                if len(seg) > 2 * xf:
                    seg[-xf:] *= np.linspace(1.0, 0.0, xf)
                pieces.append(seg)
                prev_smp = cut_smp
            pieces.append(np.zeros(int(round(add_s * fr)), dtype=np.float64))

        tail_seg = x_raw[prev_smp:].copy()
        if len(tail_seg) > 2 * xf and prev_smp > 0:
            tail_seg[:xf] *= np.linspace(0.0, 1.0, xf)
        pieces.append(tail_seg)
        pieces.append(np.zeros(int(round(outro_hold * fr)), dtype=np.float64))

        vo_spaced = np.concatenate(pieces)
        spaced_path = os.path.join(work_dir, "vo_spaced.wav")
        write_wav_mono(spaced_path, vo_spaced, fr)
        total_dur = round(len(vo_spaced) / float(fr), 2)

        def _map_t(t_orig: float) -> float:
            smp_orig = t_orig * fr
            sh = 0.0
            for c_smp, a_s in pauses:
                if smp_orig >= c_smp:
                    sh += a_s
            return t_orig + sh

        tokens_flat = [
            {"text": N_(x["w"]), "start": round(_map_t(float(x["s"])), 3), "end": round(_map_t(float(x["e"])), 3)}
            for x in raw_whisper
        ]
        for w_a, w_b in sent_word_ranges:
            spaced_sent_spans.append((tokens_flat[w_a]["start"], tokens_flat[w_b]["end"]))
    else:
        # Yedek yol (Whisper yoksa): -43 dB eşiğiyle sessiz harfleri koruyarak hizala
        sils, _ = ff_silences(vo_final, noise_db=-43.0, min_dur=0.18)
        spans, prev = [], 0.0
        for s, e in sils:
            if s - prev > 0.18:
                spans.append((prev, s))
            prev = e
        if dur_raw - prev > 0.18:
            spans.append((prev, dur_raw))
        if not spans:
            spans = [(0.0, dur_raw)]
        sent_raw_spans = _align_sentences_to_spans(sents, spans)

        fade_n = int(0.008 * fr)
        pieces = [np.zeros(int(round(intro_lead * fr)), dtype=np.float64)]
        cursor_samples = len(pieces[0])
        cut_points = [max(0, int(round((sent_raw_spans[0][0] - 0.06) * fr)))]
        for idx in range(len(sent_raw_spans) - 1):
            mid = 0.5 * (sent_raw_spans[idx][1] + sent_raw_spans[idx + 1][0])
            cut_points.append(min(len(x_raw), max(cut_points[-1], int(round(mid * fr)))))
        cut_points.append(min(len(x_raw), int(round((sent_raw_spans[-1][1] + 0.08) * fr))))

        for si in range(len(sents)):
            s_smp, e_smp = cut_points[si], cut_points[si + 1]
            seg = x_raw[s_smp:e_smp].copy()
            if len(seg) > fade_n * 3:
                seg[:fade_n] *= np.linspace(0.0, 1.0, fade_n)
                seg[-fade_n:] *= np.linspace(1.0, 0.0, fade_n)
            t_start = cursor_samples / float(fr)
            pieces.append(seg)
            cursor_samples += len(seg)
            t_end = cursor_samples / float(fr)
            spaced_sent_spans.append((t_start, t_end))
            if si < len(sents) - 1:
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

        for s, (st_s, en_s) in zip(sents, spaced_sent_spans):
            ws = s.split()
            weights = [_syllable_weight(w) for w in ws]
            tot_w = sum(weights) or 1.0
            usable = max(0.15, (en_s - st_s) - 0.04)
            cur_t = st_s + 0.02
            for w_txt, ww in zip(ws, weights):
                wd = usable * ww / tot_w
                tokens_flat.append({"text": N_(w_txt), "start": round(cur_t, 3), "end": round(cur_t + wd, 3)})
                cur_t += wd

    chunks = build_auto_subtitle_chunks(tokens_flat)
    last_word_end = tokens_flat[-1]["end"] if tokens_flat else round(total_dur - outro_hold, 3)

    scene_files = _discover_scenes(work_dir, cfg)
    n_sc = len(scene_files)
    headlines = resolve_scene_headlines(cfg, sents, n_sc)

    # Cümle sınırlarıyla hizalı sahne zaman çizelgesi (render_batch_187_196.py standardı)
    scene_timeline = []
    for si in range(n_sc):
        sent_idx_start = min(len(spaced_sent_spans) - 1, int(round(si * len(spaced_sent_spans) / n_sc)))
        sent_idx_end = min(len(spaced_sent_spans) - 1, max(sent_idx_start, int(round((si + 1) * len(spaced_sent_spans) / n_sc)) - 1))
        t0 = 0.0 if si == 0 else max(0.0, spaced_sent_spans[sent_idx_start][0] - 0.10)
        t1 = total_dur if si == n_sc - 1 else max(t0 + 1.0, spaced_sent_spans[sent_idx_end][1] + 0.20)
        scene_timeline.append({
            "scene_idx": si,
            "file": scene_files[si],
            "is_closing": (si == n_sc - 1),
            "mode": si % 3,
            "start": round(t0, 3),
            "end": round(t1, 3),
            "icon": headlines[si]["icon"],
            "line1": headlines[si]["line1"],
            "line2": headlines[si]["line2"],
        })
    for si in range(len(scene_timeline) - 1):
        scene_timeline[si + 1]["start"] = scene_timeline[si]["end"]

    if v2_context is not None:
        if n_sc != EXPECTED_SCENES or len(sents) != EXPECTED_SCENES:
            raise ShortsAcceptanceError("Shorts v2 zamanlaması tam 7 görsel ve 7 cümle ister")
        interval_seconds = total_dur / EXPECTED_SCENES
        scene_timeline = []
        for si in range(EXPECTED_SCENES):
            start = round(si * interval_seconds, 3)
            end = round((si + 1) * interval_seconds, 3) if si < EXPECTED_SCENES - 1 else total_dur
            scene_timeline.append({
                "scene_idx": si,
                "file": scene_files[si],
                "is_closing": si == EXPECTED_SCENES - 1,
                "mode": si % 3,
                "start": start,
                "end": end,
                "icon": headlines[si]["icon"],
                "line1": headlines[si]["line1"],
                "line2": headlines[si]["line2"],
            })
        validate_scene_intervals(scene_timeline)

    cta_start, click_delay = endcard_v2.find_endcard_and_click_times(tokens_flat, last_word_end)
    for ch in chunks:
        if ch.get("is_cta") or ch["start"] >= cta_start - 0.05:
            ch["is_cta"] = True
            ch["hide"] = ch["show"]
        elif ch["end"] > cta_start:
            ch["end"] = round(cta_start, 3)
            ch["hide"] = round(cta_start, 3)

    out = {
        "template_version": "2.2-sablon_v2",
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
        "tokens": tokens_flat,
        "scenes": scene_timeline,
        "sentence_spans": [[round(a, 3), round(b, 3)] for a, b in spaced_sent_spans],
        "chunks": chunks,
    }
    with open(os.path.join(work_dir, "timing.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print(f"{vdir_arg}: sablon_v2 timing hazır -> {len(chunks)} altyazı bloğu, {n_sc} sahne, toplam {total_dur:.2f}s, CTA @ {cta_start:.2f}s")


# ---------------------------------------------------------------- AŞAMA 3: MUSIC (sablon_v2/build_v2_shorts.py Birebir Jenerik)
THEME_ROOT_SHIFTS = {
    "gunluk_bilim": 0,
    "uzay": -2,
    "insan_beyin": 2,
    "doga_hayvan": 5,
    "tarih_teknoloji": -3,
}


def synthesize_bilgidozu_jenerik(duration_s: float, sr: int = SR, semitone_shift: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """sablon_v2/build_v2_shorts.py birebir 116 BPM Dm9 belgesel merak jeneriği."""
    n = int(round((duration_s + 0.25) * sr))
    L = np.zeros(n, dtype=np.float64)
    R = np.zeros(n, dtype=np.float64)

    bpm = 116.0
    beat = 60.0 / bpm
    eighth = beat / 2.0
    bar = beat * 4.0
    pitch_mul = 2.0 ** (semitone_shift / 12.0)

    prog_chords = [
        [146.83, 293.66, 349.23, 440.00, 523.25, 659.25],
        [116.54, 233.08, 293.66, 349.23, 440.00, 587.33],
        [174.61, 261.63, 349.23, 440.00, 523.25, 659.25],
        [110.00, 220.00, 293.66, 329.63, 440.00, 554.37],
    ]
    prog_arps = [
        [293.66, 440.00, 587.33, 659.25, 880.00, 659.25, 587.33, 440.00],
        [233.08, 349.23, 466.16, 587.33, 698.46, 587.33, 466.16, 349.23],
        [261.63, 349.23, 523.25, 659.25, 783.99, 659.25, 523.25, 349.23],
        [220.00, 329.63, 440.00, 554.37, 659.25, 587.33, 440.00, 329.63],
    ]

    n_bars = int(math.ceil((duration_s + 0.25) / bar))
    for bi in range(n_bars):
        t0 = bi * bar
        i0 = int(t0 * sr)
        dur_b = min(bar + 0.32, (n - i0) / sr)
        if dur_b <= 0.05:
            break
        nb = int(dur_b * sr)
        lt = np.arange(nb, dtype=np.float64) / sr
        env = np.minimum(1.0, lt / 0.28) * np.minimum(1.0, (dur_b - lt) / 0.34)
        chord = prog_chords[bi % 4]

        pad_l = np.zeros(nb, dtype=np.float64)
        pad_r = np.zeros(nb, dtype=np.float64)
        for vi, f0 in enumerate(chord):
            f = f0 * pitch_mul
            wt = 0.42 if vi == 0 else (1.0 if vi in (1, 2, 3) else 0.72)
            det = 1.0028 if (vi % 2 == 0) else 0.9972
            vib = 1.0 + 0.0012 * np.sin(2.0 * math.pi * (3.6 + 0.3 * vi) * lt)
            sig_l = (
                0.68 * np.sin(2.0 * math.pi * f * vib * lt)
                + 0.24 * np.sin(2.0 * math.pi * (2.0 * f) * lt + 0.4)
                + 0.08 * np.sin(2.0 * math.pi * (3.0 * f) * lt + 0.9)
            )
            sig_r = (
                0.68 * np.sin(2.0 * math.pi * (f * det) * vib * lt + 0.55)
                + 0.24 * np.sin(2.0 * math.pi * (2.0 * f * det) * lt + 1.15)
                + 0.08 * np.sin(2.0 * math.pi * (3.0 * f * det) * lt + 1.75)
            )
            pan_l = 0.68 if (vi % 2 == 0) else 0.42
            pan_r = 0.42 if (vi % 2 == 0) else 0.68
            pad_l += wt * pan_l * sig_l
            pad_r += wt * pan_r * sig_r

        L[i0:i0 + nb] += 0.20 * pad_l * env
        R[i0:i0 + nb] += 0.20 * pad_r * env

    n_eighths = int((duration_s + 0.1) / eighth)
    for ei in range(n_eighths):
        t0 = ei * eighth
        i0 = int(t0 * sr)
        bar_idx = (ei // 8) % 4
        step_idx = ei % 8
        f = prog_arps[bar_idx][step_idx] * pitch_mul
        nd = min(int(0.42 * sr), n - i0)
        if nd <= 32:
            break
        lt = np.arange(nd, dtype=np.float64) / sr
        att = np.minimum(1.0, lt / 0.005)
        dec1 = np.exp(-lt * 8.5)
        dec2 = np.exp(-lt * 22.0)
        pluck = att * (
            0.66 * np.sin(2.0 * math.pi * f * lt) * dec1
            + 0.26 * np.sin(2.0 * math.pi * (2.0 * f) * lt) * dec1
            + 0.11 * np.sin(2.0 * math.pi * (3.0 * f) * lt) * dec2
            + 0.05 * np.sin(2.0 * math.pi * (4.0 * f) * lt) * np.exp(-lt * 35.0)
        )
        accent = 1.18 if (step_idx in (0, 3, 6)) else 0.82
        pan = 0.32 + 0.36 * (0.5 + 0.5 * math.sin(ei * 1.15))
        L[i0:i0 + nd] += 0.34 * accent * pan * pluck
        R[i0:i0 + nd] += 0.34 * accent * (1.0 - pan) * pluck

    n_beats = int(duration_s / beat)
    rng = np.random.default_rng(2026)
    for qi in range(n_beats):
        t0 = qi * beat
        i0 = int(t0 * sr)
        if qi % 2 == 0:
            kd = min(int(0.18 * sr), n - i0)
            if kd > 16:
                kt = np.arange(kd, dtype=np.float64) / sr
                f_sw = 58.0 + 55.0 * np.exp(-kt * 28.0)
                ph = 2.0 * math.pi * np.cumsum(f_sw) / sr
                kick = (0.72 * np.sin(ph) + 0.28 * np.sin(2.0 * ph)) * np.exp(-kt * 16.0) * np.minimum(1.0, kt / 0.004)
                L[i0:i0 + kd] += 0.22 * kick
                R[i0:i0 + kd] += 0.22 * kick

        i_off = int((t0 + eighth) * sr)
        td = min(int(0.032 * sr), n - i_off)
        if td > 8:
            tt = np.arange(td, dtype=np.float64) / sr
            tick = (0.55 * np.sin(2.0 * math.pi * 2350.0 * tt) + 0.45 * rng.standard_normal(td)) * np.exp(-tt * 130.0)
            L[i_off:i_off + td] += 0.045 * tick
            R[i_off:i_off + td] += 0.055 * tick

    for t_h, f_h0 in ((0.00, 587.33), (0.09, 880.00), (0.18, 1174.66)):
        f_h = f_h0 * pitch_mul
        ih = int(t_h * sr)
        hd = min(int(0.55 * sr), n - ih)
        if hd > 16:
            ht = np.arange(hd, dtype=np.float64) / sr
            bell = np.minimum(1.0, ht / 0.004) * (
                0.70 * np.sin(2.0 * math.pi * f_h * ht) * np.exp(-ht * 6.5)
                + 0.30 * np.sin(2.0 * math.pi * 2.0 * f_h * ht) * np.exp(-ht * 12.0)
            )
            L[ih:ih + hd] += 0.22 * bell
            R[ih:ih + hd] += 0.22 * bell

    t_outro = max(0.0, duration_s - 1.15)
    io = int(t_outro * sr)
    od = min(int(1.12 * sr), n - io)
    if od > 32:
        ot = np.arange(od, dtype=np.float64) / sr
        env_o = np.minimum(1.0, ot / 0.06) * np.exp(-ot * 2.4) * np.minimum(1.0, (od / sr - ot) / 0.18)
        chord_end = np.zeros(od, dtype=np.float64)
        for f_o0 in (293.66, 440.00, 587.33, 698.46, 880.00):
            f_o = f_o0 * pitch_mul
            chord_end += 0.22 * np.sin(2.0 * math.pi * f_o * ot) + 0.08 * np.sin(2.0 * math.pi * 2.0 * f_o * ot)
        L[io:io + od] += 0.28 * chord_end * env_o
        R[io:io + od] += 0.28 * chord_end * env_o

    total_n = int(round(duration_s * sr))
    L = L[:total_n]
    R = R[:total_n]

    fade_n = min(total_n, int(0.25 * sr))
    fade = np.linspace(1.0, 0.22, fade_n)
    L[-fade_n:] *= fade
    R[-fade_n:] *= fade

    cur_rms = math.sqrt(0.5 * (float(np.mean(L * L)) + float(np.mean(R * R))) + 1e-12)
    target_rms = 10.0 ** (-14.8 / 20.0)
    L *= target_rms / cur_rms
    R *= target_rms / cur_rms
    return L, R


def one_pole_lowpass(sig: np.ndarray, cutoff_hz: float = 850.0, sr: int = SR) -> np.ndarray:
    taps = 63
    fc = cutoff_hz / sr
    n = np.arange(taps) - (taps - 1) / 2.0
    h = np.sinc(2.0 * fc * n) * np.hanning(taps)
    h /= np.sum(h)
    return np.convolve(sig, h, mode="same")


def stage_music(vdir_arg: str, explicit_cfg_path: str | None = None):
    work_dir, cfg, _ = _resolve_context(vdir_arg, explicit_cfg_path)
    tl_path = os.path.join(work_dir, "timing.json")
    dur = json.load(open(tl_path, encoding="utf-8"))["total"] if os.path.exists(tl_path) else 42.0
    theme_key = str(cfg.get("music_theme") or "gunluk_bilim")
    shift = THEME_ROOT_SHIFTS.get(theme_key, 0)
    mL, mR = synthesize_bilgidozu_jenerik(dur, sr=SR, semitone_shift=shift)
    st = np.stack([mL, mR], axis=1)
    out_p = os.path.join(work_dir, "music.wav")
    pcm = np.clip(st * 32767.0, -32768, 32767).astype(np.int16)
    with wave.open(out_p, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(pcm.tobytes())
    print(f"music [sablon_v2 Dm9 116BPM jenerik | theme={theme_key}]: {out_p} ({dur:.2f}s)")


def _measure_lufs(wav_path: str) -> float:
    r = subprocess.run(
        [FF, "-hide_banner", "-i", wav_path, "-af", "loudnorm=print_format=json", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    m = re.search(r'"input_i"\s*:\s*"([^"]+)"', r.stderr)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    r2 = subprocess.run([FF, "-hide_banner", "-i", wav_path, "-af", "ebur128", "-f", "null", "-"],
                        capture_output=True, text=True)
    ms = re.findall(r"I:\s*(-?[0-9.]+)\s*LUFS", r2.stderr)
    return float(ms[-1]) if ms else -15.5


def build_mix(work_dir: str, tl: dict, cfg: dict | None = None) -> str:
    """sablon_v2/build_v2_shorts.py + render_batch_187_196.py birebir auto-ducking broadcast miksajı."""
    total_dur = float(tl["total"])
    target_n = int(round(total_dur * SR))
    vo_file = os.path.join(work_dir, tl.get("vo_file", "vo_spaced.wav"))
    if not os.path.exists(vo_file):
        vo_file = os.path.join(work_dir, "vo_final.wav")
    vo_mono, _ = read_wav_mono(vo_file)
    if len(vo_mono) < target_n:
        vo_mono = np.pad(vo_mono, (0, target_n - len(vo_mono)))
    else:
        vo_mono = vo_mono[:target_n]

    tokens = tl.get("tokens") or [
        {"text": w["w"], "start": w["s"], "end": w["e"]}
        for ch in (tl.get("chunks") or [])
        for w in (ch.get("words") or [])
    ]

    speech_only = np.zeros(target_n, dtype=np.float64)
    for tk in tokens:
        a = max(0, int((float(tk["start"]) - 0.045) * SR))
        b = min(target_n, int((float(tk["end"]) + 0.060) * SR))
        speech_only[a:b] = 1.0

    # Kelime sonu sessiz harflerini ASLA kırpma: yalnız ilk konuşma öncesi ve son konuşma sonrası dijital sıfırla
    v_clean = vo_mono.copy()
    if tokens:
        head_zero = max(0, int((float(tokens[0]["start"]) - 0.14) * SR))
        tail_zero = min(target_n, int((float(tokens[-1]["end"]) + 0.22) * SR))
        if head_zero > 0:
            v_clean[:head_zero] = 0.0
        if tail_zero < target_n:
            v_clean[tail_zero:] = 0.0

    active_samples = v_clean[np.abs(v_clean) > 0.012]
    sp_rms_val = float(np.sqrt(np.mean(active_samples ** 2)) + 1e-9) if len(active_samples) > 100 else 0.16
    v_clean = np.clip(v_clean * (0.195 / sp_rms_val), -0.88, 0.88)
    vL = v_clean.copy()
    vR = v_clean.copy()

    hop = int(0.010 * SR)
    win = int(0.025 * SR)
    n_hops = int(math.ceil(target_n / hop))
    sp_rms = np.zeros(n_hops, dtype=np.float64)
    sp_tok = np.zeros(n_hops, dtype=np.float64)
    for hi in range(n_hops):
        c0 = hi * hop
        c1 = min(target_n, c0 + win)
        seg = v_clean[c0:c1]
        sp_rms[hi] = math.sqrt(float(np.mean(seg * seg)) + 1e-12) if len(seg) else 0.0
        sp_tok[hi] = float(np.max(speech_only[c0:c1])) if len(seg) else 0.0

    thresh = 10.0 ** (-33.0 / 20.0)
    raw_active = ((sp_tok > 0.5) | (sp_rms > thresh)).astype(np.float64)
    active_la = np.zeros(n_hops, dtype=np.float64)
    for hi in range(n_hops):
        active_la[hi] = float(np.max(raw_active[hi:min(n_hops, hi + 6)]))

    target_gain = np.where(active_la > 0.5, DUCK_FLOOR, 1.0)
    alpha_att = math.exp(-0.010 / 0.070)
    alpha_rel = math.exp(-0.010 / 0.140)
    gain_hops = np.ones(n_hops, dtype=np.float64)
    g = 1.0
    for hi in range(n_hops):
        tg = target_gain[hi]
        g = (alpha_att * g + (1.0 - alpha_att) * tg) if tg < g else (alpha_rel * g + (1.0 - alpha_rel) * tg)
        gain_hops[hi] = g

    hop_centers = np.minimum(target_n - 1, np.arange(n_hops) * hop + hop // 2)
    duck_curve = np.interp(np.arange(target_n), hop_centers, gain_hops)
    bright_mix = np.clip((duck_curve - DUCK_FLOOR) / (1.0 - DUCK_FLOOR), 0.0, 1.0)

    theme_key = str((cfg or {}).get("music_theme") or "gunluk_bilim")
    shift = THEME_ROOT_SHIFTS.get(theme_key, 0)
    mL_bright, mR_bright = synthesize_bilgidozu_jenerik(total_dur, sr=SR, semitone_shift=shift)
    mL_warm = one_pole_lowpass(mL_bright, cutoff_hz=720.0, sr=SR) * 1.10
    mR_warm = one_pole_lowpass(mR_bright, cutoff_hz=720.0, sr=SR) * 1.10
    mL_ducked = (mL_warm * (1.0 - bright_mix) + mL_bright * bright_mix) * duck_curve
    mR_ducked = (mR_warm * (1.0 - bright_mix) + mR_bright * bright_mix) * duck_curve

    mixL = vL + mL_ducked
    mixR = vR + mR_ducked

    cta_t = float(tl.get("cta_start", max(1.0, total_dur - 2.6)))
    click_delay = float(tl.get("cta_click_delay", 1.25))
    sfx_st = endcard_v2.synthesize_endcard_sfx(click_delay=click_delay, sr=SR)
    s0 = max(0, int(round(cta_t * SR)))
    if s0 < target_n:
        s1 = min(target_n, s0 + len(sfx_st))
        mixL[s0:s1] += sfx_st[:s1 - s0, 0]
        mixR[s0:s1] += sfx_st[:s1 - s0, 1]

    pre_wav = os.path.join(work_dir, "mix_pre.wav")
    peak0 = max(float(np.max(np.abs(mixL))), float(np.max(np.abs(mixR))), 1e-9)
    pre_scale = min(1.0, 0.92 / peak0)
    inter0 = np.empty(target_n * 2, dtype=np.int16)
    inter0[0::2] = np.clip(mixL * pre_scale * 32767.0, -32768, 32767).astype(np.int16)
    inter0[1::2] = np.clip(mixR * pre_scale * 32767.0, -32768, 32767).astype(np.int16)
    with wave.open(pre_wav, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(inter0.tobytes())

    cur_lufs = _measure_lufs(pre_wav)
    with contextlib.suppress(OSError):
        os.unlink(pre_wav)
    lin_gain = pre_scale * (10.0 ** ((TARGET_LUFS - cur_lufs) / 20.0))

    ceil = 10.0 ** (-1.2 / 20.0)
    finL = ceil * np.tanh((mixL * lin_gain) / ceil)
    finR = ceil * np.tanh((mixR * lin_gain) / ceil)

    mix_path = os.path.join(work_dir, "mix.wav")
    inter_fin = np.empty(target_n * 2, dtype=np.int16)
    inter_fin[0::2] = np.clip(finL * 32767.0, -32768, 32767).astype(np.int16)
    inter_fin[1::2] = np.clip(finR * 32767.0, -32768, 32767).astype(np.int16)
    with wave.open(mix_path, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(inter_fin.tobytes())

    intro_sl = slice(int(0.05 * SR), min(target_n, int(1.30 * SR)))
    sp_mask = speech_only > 0.5
    m_st = 0.5 * ((mL_ducked * lin_gain) ** 2 + (mR_ducked * lin_gain) ** 2)
    d_intro = 10.0 * math.log10(float(np.mean(m_st[intro_sl])) + 1e-12)
    d_sp = 10.0 * math.log10(float(np.mean(m_st[sp_mask])) + 1e-12) if np.any(sp_mask) else -31.0
    final_lufs = _measure_lufs(mix_path)
    with open(os.path.join(work_dir, "audio_qc.json"), "w", encoding="utf-8") as fh:
        json.dump({
            "integrated_lufs": round(final_lufs, 2),
            "intro_music_dbfs": round(d_intro, 2),
            "speech_music_dbfs": round(d_sp, 2),
            "ducking_amount_db": round(d_intro - d_sp, 2),
        }, fh, indent=2)
    print(f"[Auto-Duck QA] LUFS={final_lufs:.2f} | intro={d_intro:.1f} dBFS | speech={d_sp:.1f} dBFS | duck={d_intro - d_sp:.1f} dB")
    return mix_path


# ---------------------------------------------------------------- AŞAMA 4: RENDER (render_batch_187_196.py Birebir Kompozit)
def render_video(vdir_arg: str, explicit_cfg_path: str | None = None):
    work_dir, cfg, _ = _resolve_context(vdir_arg, explicit_cfg_path)
    v2_context = validate_v2_production_context(work_dir, cfg)
    with open(os.path.join(work_dir, "timing.json"), encoding="utf-8") as fh:
        tl = json.load(fh)
    total_dur = float(tl["total"])
    if v2_context is not None:
        validate_duration(total_dur)
        validated_intervals = validate_scene_intervals(tl.get("scenes") or [])
        if abs(validated_intervals[-1]["end"] - total_dur) > 1e-3:
            raise ShortsAcceptanceError("V2 son sahne bitişi MP4 toplam süresiyle uyuşmuyor")
    n_frames = max(1, int(round(total_dur * FPS)))

    scenes_tl = tl.get("scenes") or []
    if not scenes_tl:
        raise RuntimeError("timing.json içinde 'scenes' eksik; önce `timing` çalıştırın.")

    scenes = []
    headlines = []
    for idx, sc in enumerate(scenes_tl):
        src_file = os.path.join(work_dir, sc["file"])
        is_cl = bool(sc.get("is_closing"))
        pp = os.path.join(work_dir, "plate_closing_cta.jpg" if is_cl else ("plate_" + sc["file"]))
        if os.path.exists(pp):
            pl = Image.open(pp).convert("RGB")
        else:
            pl = prepare_fullscreen_plate(src_file, is_closing=is_cl)
        scenes.append({
            "start": float(sc["start"]),
            "end": float(sc["end"]),
            "plate": pl,
            "mode": int(sc.get("mode", idx % 3)),
        })
        headlines.append({
            "start": float(sc["start"]),
            "end": float(sc["end"]),
            "card": render_headline_card(sc["icon"], sc["line1"], sc["line2"]),
        })

    chunks = tl.get("chunks") or []
    visible_chunks = [ch for ch in chunks if not ch.get("is_cta") and ch.get("tokens")]
    sub_cache = {
        (ci, ti): render_subtitle_state(ch, ti)
        for ci, ch in enumerate(visible_chunks)
        for ti in range(-1, len(ch["tokens"]))
    }

    # Kaynak satırı yalnızca doğrulanmış HTTPS URL'sinden; stok görsel kredisi sahneye göre yazılır.
    source_url = _verified_source_url_format(cfg.get("source_url") or "")
    visual_credits = cfg.get("visual_credits") or []
    static_overlays = []
    for scene_index in range(len(scenes)):
        credit = visual_credits[scene_index] if scene_index < len(visual_credits) else None
        if isinstance(credit, dict):
            provider = str(credit.get("provider") or "").lower()
            url = str(credit.get("url") or "").strip()
            host_ok = ((provider == "pexels" and url.lower().startswith(("https://www.pexels.com/", "https://pexels.com/")))
                       or (provider == "pixabay" and url.lower().startswith(("https://pixabay.com/", "https://www.pixabay.com/"))))
            note2 = f"Görsel temsildir • {provider.capitalize()}: {url}" if host_ok and url.startswith("https://") else ""
        else:
            note2 = ""
        note1 = f"Kaynak URL: {source_url}" if source_url else ""
        static_overlays.append(build_static_overlay(note1_txt=note1, note2_txt=note2))
    if not static_overlays:
        static_overlays = [build_static_overlay()]

    t_endcard = float(tl.get("cta_start", max(1.0, total_dur - 2.6)))
    click_delay = float(tl.get("cta_click_delay", 1.25))

    mix_path = build_mix(work_dir, tl, cfg=cfg)
    out_mp4 = os.path.join(work_dir, "video.mp4")

    cmd = [
        FF, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
        "-i", mix_path, "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
        "-maxrate", "4200k", "-bufsize", "8400k", "-threads", "4",
        "-pix_fmt", "yuv420p", "-profile:v", "high",
        "-c:a", "aac", "-b:a", "192k", "-ar", str(SR), "-ac", "2",
        "-movflags", "+faststart", "-shortest", out_mp4,
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    XFD = 0.36

    for fn in range(n_frames):
        t = fn / float(FPS)
        cur_si = 0
        for si, sc in enumerate(scenes):
            if sc["start"] <= t <= sc["end"] + 1e-6:
                cur_si = si
                break
        sc = scenes[cur_si]
        prog = (t - sc["start"]) / max(0.01, sc["end"] - sc["start"])
        bg = sample_fullscreen_kb(sc["plate"], prog, sc["mode"])

        if cur_si > 0 and (t - sc["start"]) < XFD:
            prev_sc = scenes[cur_si - 1]
            alpha_xf = (t - sc["start"]) / XFD
            alpha_xf = alpha_xf * alpha_xf * (3.0 - 2.0 * alpha_xf)
            prev_bg = sample_fullscreen_kb(prev_sc["plate"], 1.0, prev_sc["mode"])
            bg = Image.blend(prev_bg, bg, alpha_xf)

        bg = endcard_v2.blur_bg_for_endcard(bg, t, t_endcard, W=W)
        ui_mul = endcard_v2.ui_fade_multiplier(t, t_endcard)

        frame = bg.convert("RGBA")

        if ui_mul > 0.02:
            if ui_mul >= 0.99:
                static_ov = static_overlays[min(cur_si, len(static_overlays) - 1)]
                frame = Image.alpha_composite(frame, static_ov)
            else:
                static_ov = static_overlays[min(cur_si, len(static_overlays) - 1)]
                r_s, g_s, b_s, a_s = static_ov.split()
                st_faded = Image.merge("RGBA", (r_s, g_s, b_s, a_s.point(lambda p: int(p * ui_mul))))
                frame = Image.alpha_composite(frame, st_faded)

            fill_w = max(S_(8), int(round(S_(960) * (fn / max(1, n_frames - 1)))))
            ImageDraw.Draw(frame).rounded_rectangle(
                [S_(78), S_(48), S_(78) + fill_w - 1, S_(55)],
                radius=S_(4),
                fill=(227, 244, 36, int(255 * ui_mul)),
            )

            cur_hi = 0
            for hi, hl in enumerate(headlines):
                if hl["start"] <= t <= hl["end"] + 1e-6:
                    cur_hi = hi
                    break
            hl = headlines[cur_hi]
            h_card = hl["card"]
            dt_h = t - hl["start"]
            op_h = (min(1.0, max(0.0, dt_h / 0.18)) if (cur_hi > 0 and dt_h < 0.18) else 1.0) * ui_mul
            if op_h < 0.99:
                r_c, g_c, b_c, a_c = h_card.split()
                h_card = Image.merge("RGBA", (r_c, g_c, b_c, a_c.point(lambda p: int(p * op_h))))
            frame.alpha_composite(h_card, (0, S_(268)))

            active_ci = None
            for ci, ch in enumerate(visible_chunks):
                if ch["start"] - 0.08 <= t <= min(ch["end"], t_endcard):
                    active_ci = ci
                    break

            if active_ci is not None:
                ch = visible_chunks[active_ci]
                act_ti = -1
                if ch["tokens"][0]["start"] <= t <= ch["speak_end"] + 0.06:
                    for ti, tk in enumerate(ch["tokens"]):
                        if t >= tk["start"]:
                            act_ti = ti
                sub_im = sub_cache[(active_ci, act_ti)]
                dt_in = t - (ch["start"] - 0.08)
                op_s = (min(1.0, max(0.0, dt_in / 0.08)) if dt_in < 0.08 else 1.0) * ui_mul
                if op_s < 0.99:
                    r_c, g_c, b_c, a_c = sub_im.split()
                    sub_im = Image.merge("RGBA", (r_c, g_c, b_c, a_c.point(lambda p: int(p * op_s))))
                frame.alpha_composite(sub_im, (0, S_(1115)))

        endcard_v2.composite_endcard(frame, t, t_endcard, click_delay=click_delay, W=W, H=H)

        try:
            proc.stdin.write(frame.convert("RGB").tobytes())  # type: ignore[union-attr]
        except BrokenPipeError:
            print(f"[render] {vdir_arg}: ffmpeg erken kapandı ({fn}/{n_frames})", flush=True)
            break
        if fn % 300 == 0:
            print(f"{vdir_arg} frame {fn}/{n_frames}", flush=True)

    with contextlib.suppress(Exception):
        proc.stdin.close()  # type: ignore[union-attr]
    rc = proc.wait()
    scenes.clear()
    sub_cache.clear()
    gc.collect()
    if rc != 0:
        raise RuntimeError(f"ffmpeg render hata kodu: {rc}")
    print(f"done: {out_mp4} ({os.path.getsize(out_mp4) / 1e6:.2f} MB)")

    if v2_context is not None:
        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            raise ShortsAcceptanceError("FFprobe yok; v2 MP4 süresi doğrulanamadı")
        probe = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", out_mp4],
            check=True, capture_output=True, text=True, timeout=60,
        )
        mp4_duration = validate_duration(probe.stdout.strip())
        if abs(mp4_duration - total_dur) > 0.75:
            raise ShortsAcceptanceError(
                f"Gerçek MP4 süresi zaman çizelgesinden sapıyor: {mp4_duration:.3f}s / {total_dur:.3f}s"
            )
        image_hashes = [
            {"file": name, "sha256": sha256_file(os.path.join(work_dir, name))}
            for name in cfg["scenes"]
        ]
        render_manifest = {
            "version": 2,
            "production_mode": "production_v2",
            "shorts_version": cfg["shorts_version"],
            "template_version": cfg["template_version"],
            "voice_provider": v2_context["voice_provider"],
            "voice_provenance_status": v2_context["voice_provenance_status"],
            "voice_speed_factor": v2_context["voice_speed_factor"],
            "voice_raw_sha256": v2_context["voice_raw_sha256"],
            "voice_render_sha256": sha256_file(os.path.join(work_dir, "vo_final.wav")),
            "mix_sha256": sha256_file(mix_path),
            "images": image_hashes,
            "mp4_sha256": sha256_file(out_mp4),
            "mp4_duration_seconds": mp4_duration,
        }
        with open(os.path.join(work_dir, "render_manifest_v2.json"), "w", encoding="utf-8") as fh:
            json.dump(render_manifest, fh, ensure_ascii=False, indent=2)
        validate_render_manifest_v2(work_dir, cfg, mp4_duration)


# ---------------------------------------------------------------- AŞAMA 5: COVER (kapak.py Birebir 1080x1920 Dikey Kapak)
def stage_cover(vdir_arg: str, explicit_cfg_path: str | None = None):
    work_dir, cfg, _ = _resolve_context(vdir_arg, explicit_cfg_path)
    scenes = _discover_scenes(work_dir, cfg)
    src_p = os.path.join(work_dir, scenes[0])
    out_cov = os.path.join(work_dir, "kapak.jpg")
    raw_lines = _flatten_title_lines(cfg.get("cover_lines") or cfg.get("title") or cfg.get("title_lines"))
    if not raw_lines:
        raw_lines = ["BİLİMSEL", "GERÇEK!"]
    try:
        import kapak as kapak_mod
        kapak_mod.kapak_uret(src_p, out_cov, satirlar=raw_lines[:3], kategori="BİLİM & KEŞİF", alt_aciklama="")
    except Exception:
        im = prepare_fullscreen_plate(src_p, is_closing=False).resize((1080, 1920), Image.Resampling.LANCZOS)
        im.save(out_cov, quality=93)
    print(f"cover: {out_cov}")
    return out_cov


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    stage = sys.argv[1]
    vdir_arg = sys.argv[2]
    explicit_cfg = sys.argv[3] if len(sys.argv) > 3 else None

    if stage in {"all", "timing", "render"}:
        gate_work_dir, gate_cfg, _ = _resolve_context(vdir_arg, explicit_cfg)
        validate_v2_production_context(gate_work_dir, gate_cfg)

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
