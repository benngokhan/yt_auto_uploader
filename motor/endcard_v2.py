#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BİLGİ DOZU ONAYLI SAF 3D KAPANIŞ EKRANI (END-CARD v2.2)

Kullanıcının kilitlediği tam kural:
  1) Anlatıcı son kapanış cümlesine ("Daha fazla Bilgi Dozu için takip et!" /
     "...Bilgi Dozu'nu takip et!") GİRER GİRMEZ ekran kararır.
  2) Kapanış ekranında ÜSTTEKİ YEŞİL ÇUBUK, SOL ÜST ROZET, BAŞLIK, ALTYAZI VE
     ALTTAKİ KAYNAK YAZILARI DAHİL HİÇBİR ŞEY KALMAZ — %100 temiz karanlık sahne
     üzerinde SADECE bu 3D animasyon yer alır.
  3) "Daha fazla Bilgi Dozu..." okunurken 3D `Bilgi [Dozu]` logosu ve altında
     3D `[ ▶ TAKİP ET ]` butonu yaylanarak açılır; fare imleci sağ alttan kayarak
     yaklaşır ve tam "takip et!" dendiği anda butona tıklar (fiziksel basılma +
     çift halkalı kırmızı/sarı şok dalgası + cam parlama + fare tık & onay tınısı).
"""

import math
import os
import re
import unicodedata
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
ASSET_DIR = os.path.join(HERE, "endcard_assets")

OUTRO_HOLD_SEC = 1.45
_ASSET_CACHE = {}


def clamp01(v: float) -> float:
    return min(max(float(v), 0.0), 1.0)


def ease_out(t: float) -> float:
    return 1.0 - (1.0 - clamp01(t)) ** 3


def ease_io(t: float) -> float:
    x = clamp01(t)
    return x * x * (3.0 - 2.0 * x)


def _norm_tr(w: str) -> str:
    s = unicodedata.normalize("NFC", str(w or "")).replace("İ", "i").replace("I", "ı").lower()
    return re.sub(r"[^\wçğıöşü0-9]", "", s)


def find_endcard_and_click_times(words_flat: list, fallback_last_end: float) -> tuple:
    """Kelime listesinden (`[{"w"/"text": ..., "s"/"start": ..., "e"/"end": ...}]`):
      - `endcard_start`: 'Daha fazla Bilgi Dozu...' (veya son '...Bilgi Dozu'nu takip et!')
        ifadesinin BAŞLADIĞI an
      - `click_delay`: `endcard_start`'tan kaç saniye sonra 'takip et!' tıklamasının
        gerçekleşeceği (tam 'takip' kelimesinin okunduğu an)
    döndürür."""
    if not words_flat:
        ec = max(1.0, float(fallback_last_end) - 2.1)
        return round(ec, 3), 1.35

    def _w(item):
        return _norm_tr(item.get("w") if "w" in item else item.get("text", ""))

    def _s(item):
        return float(item.get("s") if "s" in item else item.get("start", 0.0))

    n = len(words_flat)
    tail_start_idx = max(0, n - 14)

    # 1) Son bölümde "daha" + "fazla" + "bilgi" kalıbını ara
    ec_idx = None
    for i in range(tail_start_idx, n - 1):
        if _w(words_flat[i]) == "daha" and _w(words_flat[i + 1]).startswith("fazla"):
            ec_idx = i
            break

    # 2) Yoksa son bölümde "bilgi" + "dozu*" kalıbını ara (örn. "...ve Bilgi Dozu'nu takip et!")
    if ec_idx is None:
        for i in range(tail_start_idx, n - 1):
            if _w(words_flat[i]) == "bilgi" and _w(words_flat[i + 1]).startswith("dozu"):
                ec_idx = max(tail_start_idx, i - 1) if (i > tail_start_idx and _w(words_flat[i - 1]) == "ve") else i
                break

    # 3) "takip" kelimesinin başlangıç zamanını bul
    takip_idx = None
    for i in range(n - 1, tail_start_idx - 1, -1):
        if _w(words_flat[i]).startswith("takip"):
            takip_idx = i
            break

    if ec_idx is not None:
        ec_start = max(0.5, _s(words_flat[ec_idx]) - 0.06)
    elif takip_idx is not None:
        ec_start = max(0.5, _s(words_flat[takip_idx]) - 1.15)
    else:
        ec_start = max(0.5, float(fallback_last_end) - 2.0)

    if takip_idx is not None:
        click_abs = _s(words_flat[takip_idx]) + 0.06
    else:
        click_abs = ec_start + 1.25

    click_delay = max(0.68, min(2.40, click_abs - ec_start))
    return round(ec_start, 3), round(click_delay, 3)


def _load_assets(scale: float):
    key = round(scale, 4)
    if key in _ASSET_CACHE:
        return _ASSET_CACHE[key]
    logo = Image.open(os.path.join(ASSET_DIR, "endcard_logo.png")).convert("RGBA")
    btn = Image.open(os.path.join(ASSET_DIR, "endcard_btn.png")).convert("RGBA")
    cur = Image.open(os.path.join(ASSET_DIR, "endcard_cursor.png")).convert("RGBA")
    cur_w = max(8, int(round(cur.width * 0.76 * scale)))
    cur_h = max(8, int(round(cur.height * 0.76 * scale)))
    cur_scaled = cur.resize((cur_w, cur_h), Image.LANCZOS)
    pack = {
        "logo": logo,
        "btn": btn,
        "cur_scaled": cur_scaled,
        "logo_base_w": int(round(logo.width * 0.80 * scale)),
        "logo_base_h": int(round(logo.height * 0.80 * scale)),
        "btn_base_w": int(round(btn.width * 0.76 * scale)),
        "btn_base_h": int(round(btn.height * 0.76 * scale)),
        "cur_w": cur_w,
        "cur_h": cur_h,
    }
    _ASSET_CACHE[key] = pack
    return pack


def ui_fade_multiplier(tsec: float, endcard_start: float) -> float:
    """Kapanış cümlesi başladığı anda TÜM diğer ekran öğelerini (üst yeşil çubuk,
    rozet, başlık, altyazı, alttaki kaynak ve imza) hızla %0'a indirir."""
    te = tsec - endcard_start
    if te <= 0.0:
        return 1.0
    return 1.0 - ease_io(te / 0.22)


def blur_bg_for_endcard(bg_rgb: Image.Image, tsec: float, endcard_start: float, W: int = 1080) -> Image.Image:
    """Kapanış cümlesine girer girmez arka planı derin sinematik karanlığa + blura alır."""
    te = tsec - endcard_start
    if te <= 0.0:
        return bg_rgb
    fade = ease_io(te / 0.26)
    if fade <= 0.01:
        return bg_rgb
    s = W / 1080.0
    blurred = bg_rgb.filter(ImageFilter.GaussianBlur(max(2, int(round(18 * s)))))
    blurred = ImageEnhance.Brightness(blurred).enhance(0.18)
    return Image.blend(bg_rgb, blurred, fade)


def composite_endcard(
    ov_rgba: Image.Image,
    tsec: float,
    endcard_start: float,
    click_delay: float = 1.25,
    W: int = 1080,
    H: int = 1920,
):
    """%100 temiz ekran üzerine SADECE 3D `Bilgi [Dozu]` + 3D `[▶ TAKİP ET]` +
    kayan fare tıklaması animasyonunu çizer."""
    te = tsec - endcard_start
    if te < 0.0:
        return

    s = W / 1080.0
    S_ = lambda px: max(1, int(round(px * s)))
    assets = _load_assets(s)
    d = ImageDraw.Draw(ov_rgba)

    # 1) 3D Bilgi [Dozu] Logo yaylı giriş (te = 0.00..0.30s)
    u_l = clamp01(te / 0.30)
    sc_l = 0.78 + 0.27 * ease_out(u_l) - 0.05 * (u_l ** 2)
    al_l = int(255 * ease_out(te / 0.18))
    lw_cur = max(8, int(round(assets["logo_base_w"] * sc_l)))
    lh_cur = max(8, int(round(assets["logo_base_h"] * sc_l)))
    lg_im = assets["logo"].resize((lw_cur, lh_cur), Image.LANCZOS)
    if al_l < 255:
        lg_im.putalpha(lg_im.getchannel("A").point(lambda v: v * al_l // 255))
    logo_cy = S_(790) - int(round((1.0 - ease_out(u_l)) * S_(28)))
    ov_rgba.alpha_composite(lg_im, (W // 2 - lw_cur // 2, logo_cy - lh_cur // 2))

    # 2) 3D Kırmızı [ ▶ TAKİP ET ] Butonu (te >= 0.12s) + tam `click_delay` anında Tıklama!
    if te >= 0.12:
        u_b = clamp01((te - 0.12) / 0.28)
        sc_b = 0.72 + 0.33 * ease_out(u_b) - 0.05 * (u_b ** 2)
        press_amt = 0.0
        t_p0 = click_delay - 0.02
        t_p1 = click_delay + 0.16
        if t_p0 <= te <= t_p1:
            press_amt = math.sin(math.pi * (te - t_p0) / 0.18)
            sc_b *= (1.0 - 0.078 * press_amt)
        elif te > t_p1:
            reb = max(0.0, 1.0 - (te - t_p1) / 0.22)
            sc_b *= (1.0 + 0.036 * math.sin(math.pi * (1.0 - reb)) * reb
                     + 0.014 * math.sin(2.0 * math.pi * 1.4 * (te - t_p1)))

        btn_cy = S_(1085) + int(round(press_amt * S_(5)))

        # Çift halkalı (kırmızı + sarı) şok dalgası
        if click_delay <= te <= (click_delay + 0.60):
            rp = (te - click_delay) / 0.60
            ral = int(220 * ((1.0 - rp) ** 1.55))
            rxp = int(assets["btn_base_w"] * 0.46 + S_(98) * ease_out(rp))
            ryp = int(assets["btn_base_h"] * 0.40 + S_(54) * ease_out(rp))
            d.rounded_rectangle([W // 2 - rxp, btn_cy - ryp, W // 2 + rxp, btn_cy + ryp],
                                radius=S_(36), outline=(255, 70, 70, ral), width=S_(5))
            rxp2 = int(assets["btn_base_w"] * 0.44 + S_(62) * ease_out(rp))
            ryp2 = int(assets["btn_base_h"] * 0.36 + S_(34) * ease_out(rp))
            d.rounded_rectangle([W // 2 - rxp2, btn_cy - ryp2, W // 2 + rxp2, btn_cy + ryp2],
                                radius=S_(32), outline=(227, 244, 36, int(ral * 0.85)), width=S_(3))

        bw_cur = max(8, int(round(assets["btn_base_w"] * sc_b)))
        bh_cur = max(8, int(round(assets["btn_base_h"] * sc_b)))
        bt_im = assets["btn"].resize((bw_cur, bh_cur), Image.LANCZOS)

        # Tıklama sonrası diyagonal cam parlama geçişi
        if (click_delay + 0.08) <= te <= (click_delay + 0.50):
            gp = (te - (click_delay + 0.08)) / 0.42
            bmask = bt_im.getchannel("A")
            sheen = Image.new("RGBA", bt_im.size, (0, 0, 0, 0))
            sd = ImageDraw.Draw(sheen)
            sx = int(-S_(60) + gp * (bw_cur + S_(120)))
            sd.polygon([(sx - S_(28), 0), (sx + S_(28), 0),
                        (sx - S_(8), bh_cur), (sx - S_(64), bh_cur)],
                       fill=(255, 255, 255, 135))
            sheen = sheen.filter(ImageFilter.GaussianBlur(S_(5)))
            bt_im = Image.composite(Image.alpha_composite(bt_im, sheen), bt_im, bmask)

        al_b = int(255 * ease_out((te - 0.12) / 0.16))
        if al_b < 255:
            bt_im.putalpha(bt_im.getchannel("A").point(lambda v: v * al_b // 255))
        ov_rgba.alpha_composite(bt_im, (W // 2 - bw_cur // 2, btn_cy - bh_cur // 2))

    # 3) Sağ alttan kayarak gelip tam `click_delay` anında tıklayan fare imleci!
    glide_start = max(0.24, click_delay - 0.46)
    glide_dur = max(0.28, (click_delay - 0.03) - glide_start)
    if te >= glide_start:
        u_c = ease_io((te - glide_start) / glide_dur)
        start_x, start_y = W // 2 + S_(375), S_(1450)
        target_x, target_y = W // 2 + S_(128), S_(1108)
        cx_cur = int(round(start_x + (target_x - start_x) * u_c))
        cy_cur = int(round(start_y + (target_y - start_y) * u_c))
        cur_sc = 1.0
        if (click_delay - 0.02) <= te <= (click_delay + 0.14):
            cp = math.sin(math.pi * (te - (click_delay - 0.02)) / 0.16)
            cur_sc = 1.0 - 0.14 * cp
            cx_cur += int(round(S_(3) * cp))
            cy_cur += int(round(S_(5) * cp))
        c_im = assets["cur_scaled"]
        if abs(cur_sc - 1.0) >= 0.01:
            c_im = c_im.resize((max(4, int(round(assets["cur_w"] * cur_sc))),
                                max(4, int(round(assets["cur_h"] * cur_sc)))), Image.LANCZOS)
        ov_rgba.alpha_composite(c_im, (cx_cur, cy_cur))


def synthesize_endcard_sfx(click_delay: float = 1.25, sr: int = 44100) -> np.ndarray:
    """Kapanış kartı ses efekti (stereo Nx2):
    - +0.04s: yumuşak açılış pop/whoosh (`Daha fazla Bilgi Dozu...` girişinde)
    - +click_delay: tam `takip et!` dendiği anda gerçekçi çift kademeli fare tık + onay tınısı"""
    dur = max(1.8, click_delay + 0.70)
    n = int(round(dur * sr))
    sfx = np.zeros(n, dtype=np.float64)

    p0, pln = int(0.04 * sr), int(0.12 * sr)
    pt = np.arange(pln, dtype=np.float64) / sr
    f_sw = 160.0 + 210.0 * (1.0 - np.exp(-pt * 34.0))
    sfx[p0:p0 + pln] += (np.sin(2.0 * np.pi * np.cumsum(f_sw) / sr)
                         * (1.0 - np.exp(-pt * 120.0)) * np.exp(-pt * 24.0) * 0.22)

    c0, cln = int(click_delay * sr), int(0.028 * sr)
    if c0 + cln < n:
        ct = np.arange(cln, dtype=np.float64) / sr
        click_dn = (np.sin(2.0 * np.pi * 1650.0 * ct) * 0.55
                    + np.sin(2.0 * np.pi * 3200.0 * ct) * 0.45) * np.exp(-ct * 190.0)
        sfx[c0:c0 + cln] += click_dn * 0.35

    c1, cln1 = int((click_delay + 0.08) * sr), int(0.022 * sr)
    if c1 + cln1 < n:
        ct1 = np.arange(cln1, dtype=np.float64) / sr
        click_up = (np.sin(2.0 * np.pi * 2100.0 * ct1) * 0.60
                    + np.sin(2.0 * np.pi * 3900.0 * ct1) * 0.40) * np.exp(-ct1 * 220.0)
        sfx[c1:c1 + cln1] += click_up * 0.20

    ch0, chln = int((click_delay + 0.04) * sr), int(0.32 * sr)
    if ch0 + chln < n:
        cht = np.arange(chln, dtype=np.float64) / sr
        chime = (0.58 * np.sin(2.0 * np.pi * 880.0 * cht)
                 + 0.42 * np.sin(2.0 * np.pi * 1318.5 * cht)) * (1.0 - np.exp(-cht * 110.0)) * np.exp(-cht * 11.0)
        sfx[ch0:ch0 + chln] += chime * 0.17

    return np.stack([sfx, sfx], axis=1)
