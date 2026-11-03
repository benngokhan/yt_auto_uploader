import os, sys, json, time, wave, subprocess
import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont, ImageFilter

FONT_BLACK_PATH = "/home/user/pilot_engine/fonts/Montserrat-Black.ttf"
FONT_BOLD_PATH  = "/home/user/pilot_engine/fonts/Montserrat-Bold.ttf"
EMOJI_FONT_PATH = "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"
BGM_PATH        = "/home/user/pilot_engine/audio/ambient_science_bgm.wav"

WHITE    = (255, 255, 255, 255)
YELLOW   = (255, 214, 0, 255)    # #FFD600 — Pilot sari vurgu
LIME     = (220, 255, 46, 255)   # #DCFF2E — @bilgidozuofficial neon-lime rozet/bar
DARK_INK = (10, 18, 24, 255)
CTA_RED  = (255, 34, 68, 255)

def wav_duration(path):
    with wave.open(path, "rb") as wf:
        return wf.getnframes() / float(wf.getframerate())

def apply_teal_orange_cinematic(bgr_img, warm_boost=1.0, cyan_boost=1.0):
    f = bgr_img.astype(np.float32) / 255.0
    b, g, r = f[:, :, 0], f[:, :, 1], f[:, :, 2]
    lum = 0.114 * b + 0.587 * g + 0.299 * r
    shadow_w = np.clip(1.0 - lum * 1.6, 0.0, 1.0)
    high_w   = np.clip((lum - 0.35) * 1.5, 0.0, 1.0)
    r_new = r - 0.045 * shadow_w + (0.065 * warm_boost) * high_w
    g_new = g + (0.014 * cyan_boost) * shadow_w + 0.015 * high_w
    b_new = b + (0.058 * cyan_boost) * shadow_w - 0.048 * high_w
    graded = np.stack([b_new, g_new, r_new], axis=-1)
    graded = np.clip((graded - 0.5) * 1.07 + 0.5, 0.0, 1.0)
    return (graded * 255.0).astype(np.uint8)

def sharpen_crisply(bgr):
    blur = cv2.GaussianBlur(bgr, (0, 0), 1.35)
    return cv2.addWeighted(bgr, 1.38, blur, -0.38, 0)

def add_bioluminescent_particles(bgr, seed, count=42, color_bgr=(245, 230, 80)):
    rng = np.random.default_rng(seed)
    h, w = bgr.shape[:2]
    overlay = np.zeros_like(bgr, dtype=np.float32)
    for _ in range(count):
        px = int(rng.integers(int(w * 0.07), int(w * 0.93)))
        py = int(rng.integers(int(h * 0.14), int(h * 0.86)))
        rad = int(rng.integers(2, 7))
        alpha = float(rng.uniform(0.18, 0.55))
        c = color_bgr if rng.random() > 0.3 else (90, 195, 255)
        cv2.circle(overlay, (px, py), rad, (c[0]*alpha, c[1]*alpha, c[2]*alpha), -1, cv2.LINE_AA)
    overlay = cv2.GaussianBlur(overlay, (0, 0), 2.4)
    return np.clip(bgr.astype(np.float32) + overlay, 0, 255).astype(np.uint8)

def build_6_vertical_plates(hero_path, seed_base):
    """Generates 6 visually distinct, razor-sharp 1350x2400 9:16 AI plates from the multi-zone AI illustration."""
    UPS_W, UPS_H = 1350, 2400
    raw = Image.open(hero_path).convert("RGB")
    # Upscale 2.5x first with Lanczos + crisp unsharp mask
    hi_w, hi_h = 1920, 3440
    hi_rgb = np.array(raw.resize((hi_w, hi_h), Image.Resampling.LANCZOS))
    hi_bgr = sharpen_crisply(cv2.cvtColor(hi_rgb, cv2.COLOR_RGB2BGR))

    # Deep atmospheric dark-teal blurred base for seamless blending
    amb_base = cv2.GaussianBlur(cv2.resize(hi_bgr, (UPS_W, UPS_H)), (0, 0), 42)
    amb_base = (amb_base.astype(np.float32) * 0.34 + np.array([26, 18, 6], dtype=np.float32)).astype(np.uint8)

    def crop_zone(y0_frac, y1_frac, x0_frac=0.0, x1_frac=1.0, mirror=False, warm=1.0, cyan=1.0, p_seed=1):
        y0, y1 = int(hi_h * y0_frac), int(hi_h * y1_frac)
        x0, x1 = int(hi_w * x0_frac), int(hi_w * x1_frac)
        sub = hi_bgr[y0:y1, x0:x1].copy()
        if mirror:
            sub = cv2.flip(sub, 1)
        # Fit preserving aspect ratio over atmospheric dark-teal canvas with soft vertical feathering
        sh, sw = sub.shape[:2]
        target_r = UPS_W / float(UPS_H)
        cur_r = sw / float(sh)
        if cur_r > target_r:
            # Subject is wider than 9:16 -> fit height to ~82% of UPS_H and feather top/bottom into dark teal
            fit_h = int(UPS_H * 0.80)
            fit_w = int(sw * (fit_h / float(sh)))
            resized = sharpen_crisply(cv2.resize(sub, (fit_w, fit_h), interpolation=cv2.INTER_LANCZOS4))
            ox = (fit_w - UPS_W) // 2
            fg = resized[:, max(0, ox):max(0, ox)+UPS_W]
            if fg.shape[1] < UPS_W:
                fg = cv2.resize(fg, (UPS_W, fit_h), interpolation=cv2.INTER_LANCZOS4)
            canvas = amb_base.copy().astype(np.float32)
            oy = (UPS_H - fit_h) // 2
            mask = np.ones((fit_h, UPS_W, 1), dtype=np.float32)
            f_px = 210
            mask[:f_px, :, 0] = np.linspace(0.0, 1.0, f_px)[:, None] ** 1.4
            mask[-f_px:, :, 0] = np.linspace(1.0, 0.0, f_px)[:, None] ** 1.4
            canvas[oy:oy+fit_h] = canvas[oy:oy+fit_h] * (1.0 - mask) + fg.astype(np.float32) * mask
            out = canvas.astype(np.uint8)
        else:
            # Center-crop to 9:16
            new_h = int(sw / target_r)
            if new_h <= sh:
                off = (sh - new_h) // 2
                sub = sub[off:off+new_h, :]
            out = sharpen_crisply(cv2.resize(sub, (UPS_W, UPS_H), interpolation=cv2.INTER_LANCZOS4))

        out = apply_teal_orange_cinematic(out, warm_boost=warm, cyan_boost=cyan)
        # Do not add the old artificial microscope lens ring/vignette. The thin
        # cyan outline crossed the third scene in otherwise unrelated videos.
        out = add_bioluminescent_particles(out, seed=seed_base * 17 + p_seed, count=36)
        return out

    return [
        crop_zone(0.00, 1.00, 0.00, 1.00, mirror=False, warm=1.00, cyan=1.10, p_seed=1),  # S1: Full dramatic hero
        crop_zone(0.00, 0.56, 0.16, 0.84, mirror=False, warm=0.95, cyan=1.25, p_seed=2),  # S2: Full-bleed upper close-up
        crop_zone(0.22, 0.78, 0.14, 0.86, mirror=False, warm=1.05, cyan=1.15, p_seed=3),  # S3: Full-bleed mid close-up, no lens ring
        crop_zone(0.44, 1.00, 0.16, 0.84, mirror=False, warm=1.35, cyan=1.05, p_seed=4),  # S4: Full-bleed lower close-up
        crop_zone(0.12, 0.88, 0.08, 0.92, mirror=True,  warm=1.10, cyan=1.18, p_seed=5),  # S5: Mirrored medium-wide
        crop_zone(0.03, 0.97, 0.00, 1.00, mirror=True,  warm=1.00, cyan=1.25, p_seed=6),  # S6: Closing wide CTA frame
    ]

def build_9_horizontal_plates(hero_9x16_path, extra_16x9_path, seed_base):
    """Generates 9 visually distinct 2400x1350 16:9 widescreen AI plates for Uzun episodes."""
    UPS_W, UPS_H = 2400, 1350
    raw = Image.open(hero_9x16_path).convert("RGB")
    hi_w, hi_h = 1920, 3440
    hi_bgr = sharpen_crisply(cv2.cvtColor(np.array(raw.resize((hi_w, hi_h), Image.Resampling.LANCZOS)), cv2.COLOR_RGB2BGR))

    # Build atmospheric widescreen backdrop from blurred + darkened hero wings
    amb = cv2.GaussianBlur(cv2.resize(hi_bgr, (UPS_W, UPS_H)), (0, 0), 48)
    amb = (amb.astype(np.float32) * 0.35 + np.array([28, 19, 7], dtype=np.float32)).astype(np.uint8)

    def make_wide_from_zone(y0_f, y1_f, align="center", mirror=False, warm=1.0, cyan=1.1, p_seed=1):
        y0, y1 = int(hi_h * y0_f), int(hi_h * y1_f)
        sub = hi_bgr[y0:y1, :].copy()
        if mirror:
            sub = cv2.flip(sub, 1)
        sh, sw = sub.shape[:2]
        # If zone is close to 16:9 (e.g. y span ~ 0.32 of 3440 = 1100px vs 1920px wide -> 1.745 ~ 16:9!), direct full-bleed!
        cur_r = sw / float(sh)
        target_r = UPS_W / float(UPS_H)  # 1.777
        if cur_r >= target_r * 0.82:
            new_h = min(sh, int(sw / target_r))
            off = (sh - new_h) // 2
            crop = sub[off:off+new_h, :]
            out = sharpen_crisply(cv2.resize(crop, (UPS_W, UPS_H), interpolation=cv2.INTER_LANCZOS4))
        else:
            # Compose crisp foreground + atmospheric wing blend
            canvas = amb.copy().astype(np.float32)
            fit_h = UPS_H
            fit_w = int(sw * (fit_h / float(sh)))
            fg = sharpen_crisply(cv2.resize(sub, (fit_w, fit_h), interpolation=cv2.INTER_LANCZOS4)).astype(np.float32)
            x0 = (UPS_W - fit_w) // 2 if align == "center" else (int(UPS_W * 0.14) if align == "left" else int(UPS_W * 0.86 - fit_w))
            x0 = max(0, min(UPS_W - fit_w, x0))
            mask = np.ones((fit_h, fit_w, 1), dtype=np.float32)
            f_px = min(220, fit_w // 4)
            mask[:, :f_px, 0] = np.linspace(0.0, 1.0, f_px)[None, :] ** 1.3
            mask[:, -f_px:, 0] = np.linspace(1.0, 0.0, f_px)[None, :] ** 1.3
            canvas[:, x0:x0+fit_w] = canvas[:, x0:x0+fit_w] * (1.0 - mask) + fg * mask
            out = canvas.astype(np.uint8)
        out = apply_teal_orange_cinematic(out, warm_boost=warm, cyan_boost=cyan)
        return add_bioluminescent_particles(out, seed=seed_base * 31 + p_seed, count=48)

    plates = [
        make_wide_from_zone(0.28, 0.62, "center", False, 1.00, 1.12, 1),  # Ch1: Mid hero widescreenband
        make_wide_from_zone(0.00, 0.34, "center", False, 0.95, 1.22, 2),  # Ch2: Upper brain/anatomy widescreenband
        make_wide_from_zone(0.45, 0.79, "center", False, 1.10, 1.15, 3),  # Ch3: Mid-lower mechanism widescreenband
        make_wide_from_zone(0.66, 1.00, "center", False, 1.30, 1.05, 4),  # Ch4: Deep microscopic widescreenband
        make_wide_from_zone(0.16, 0.50, "center", True,  1.05, 1.18, 5),  # Ch5: Mirrored upper-mid transition
    ]
    if extra_16x9_path and os.path.exists(extra_16x9_path):
        wraw = Image.open(extra_16x9_path).convert("RGB")
        wbgr = sharpen_crisply(cv2.cvtColor(np.array(wraw.resize((UPS_W, UPS_H), Image.Resampling.LANCZOS)), cv2.COLOR_RGB2BGR))
        wbgr_m = cv2.flip(wbgr, 1)
        # Left zoom, full wide, right zoom, closing
        plates.append(add_bioluminescent_particles(apply_teal_orange_cinematic(
            sharpen_crisply(cv2.resize(wbgr[:, int(UPS_W*0.22):], (UPS_W, UPS_H), interpolation=cv2.INTER_LANCZOS4)), 1.05, 1.20), seed_base*41+6, 44))
        plates.append(add_bioluminescent_particles(apply_teal_orange_cinematic(wbgr, 1.15, 1.12), seed_base*41+7, 44))
        plates.append(add_bioluminescent_particles(apply_teal_orange_cinematic(
            sharpen_crisply(cv2.resize(wbgr[:, :int(UPS_W*0.78)], (UPS_W, UPS_H), interpolation=cv2.INTER_LANCZOS4)), 1.00, 1.22), seed_base*41+8, 44))
        plates.append(add_bioluminescent_particles(apply_teal_orange_cinematic(wbgr_m, 1.05, 1.25), seed_base*41+9, 50))
    else:
        plates.append(make_wide_from_zone(0.05, 0.42, "left",   True,  1.15, 1.20, 6))
        plates.append(make_wide_from_zone(0.34, 0.70, "right",  True,  1.00, 1.25, 7))
        plates.append(make_wide_from_zone(0.58, 0.94, "center", True,  1.25, 1.10, 8))
        plates.append(make_wide_from_zone(0.22, 0.58, "center", False, 1.05, 1.28, 9))
    return plates

def render_emoji_icon(emoji_char, target_px=60):
    efont = ImageFont.truetype(EMOJI_FONT_PATH, 109)
    canvas = Image.new("RGBA", (160, 160), (0, 0, 0, 0))
    d = ImageDraw.Draw(canvas)
    d.text((16, 16), emoji_char, font=efont, embedded_color=True)
    bbox = canvas.getbbox()
    if bbox:
        canvas = canvas.crop(bbox)
    w0, h0 = canvas.size
    scale = target_px / max(w0, h0, 1)
    return canvas.resize((max(1, int(w0 * scale)), max(1, int(h0 * scale))), Image.Resampling.LANCZOS)

def fit_font(path, text, max_width, start_size, min_size=26):
    sz = start_size
    while sz >= min_size:
        f = ImageFont.truetype(path, sz)
        bbox = f.getbbox(text)
        if (bbox[2] - bbox[0]) <= max_width:
            return f
        sz -= 2
    return ImageFont.truetype(path, min_size)

def rgba_to_bgra(pil_rgba):
    arr = np.array(pil_rgba)
    return arr[:, :, [2, 1, 0, 3]].copy()

def make_upper_title_band(W, emoji_char, line1, line2, is_wide=False):
    band_h = 210 if is_wide else 300
    txt_layer = Image.new("RGBA", (W, band_h), (0, 0, 0, 0))
    sh_layer  = Image.new("RGBA", (W, band_h), (0, 0, 0, 0))
    d_txt = ImageDraw.Draw(txt_layer)
    d_sh  = ImageDraw.Draw(sh_layer)

    em_px = 60 if is_wide else 72
    em_img = render_emoji_icon(emoji_char, target_px=em_px)
    ew, eh = em_img.size

    margin = 340 if is_wide else 140
    f1 = fit_font(FONT_BLACK_PATH, line1, W - margin - (ew + 18), start_size=(44 if is_wide else 54))
    f2 = fit_font(FONT_BLACK_PATH, line2, W - margin, start_size=(48 if is_wide else 58))

    b1 = f1.getbbox(line1)
    w1, h1 = b1[2] - b1[0], b1[3] - b1[1]
    total_row1_w = ew + 18 + w1
    x1_start = (W - total_row1_w) // 2
    y1 = 16 if is_wide else 28

    em_shadow = Image.new("RGBA", em_img.size, (0, 0, 0, 220))
    sh_layer.paste(em_shadow, (x1_start, y1 + 5), em_img)
    txt_layer.paste(em_img, (x1_start, y1), em_img)

    tx1 = x1_start + ew + 18
    ty1 = y1 + (eh - h1) // 2 - b1[1]
    d_sh.text((tx1, ty1 + 5), line1, font=f1, fill=(0, 0, 0, 235), stroke_width=6, stroke_fill=(0, 0, 0, 220))
    d_txt.text((tx1, ty1), line1, font=f1, fill=WHITE, stroke_width=2, stroke_fill=(0, 0, 0, 185))

    b2 = f2.getbbox(line2)
    w2 = b2[2] - b2[0]
    tx2 = (W - w2) // 2
    ty2 = y1 + max(eh, h1) + (14 if is_wide else 20) - b2[1]
    d_sh.text((tx2, ty2 + 5), line2, font=f2, fill=(0, 0, 0, 240), stroke_width=7, stroke_fill=(0, 0, 0, 230))
    d_txt.text((tx2, ty2), line2, font=f2, fill=YELLOW, stroke_width=2, stroke_fill=(0, 0, 0, 195))

    comb = Image.alpha_composite(sh_layer.filter(ImageFilter.GaussianBlur(radius=8)), txt_layer)
    return rgba_to_bgra(comb)

def make_subtitle_band(W, text_multiline, highlight_words=None, is_wide=False, *, active_word_index=None):
    """All-white caption, except the one word currently spoken.

    The old static ``highlight_words`` argument is intentionally ignored:
    selected keywords must never masquerade as audio-synchronized highlighting.
    Repeated words are identified by position, not by their spelling.
    """
    band_h = 175 if is_wide else 240
    txt_layer = Image.new("RGBA", (W, band_h), (0, 0, 0, 0))
    sh_layer  = Image.new("RGBA", (W, band_h), (0, 0, 0, 0))
    d_txt = ImageDraw.Draw(txt_layer)
    d_sh  = ImageDraw.Draw(sh_layer)

    lines = text_multiline.split("\n")
    base_sz = 36 if is_wide else 40
    font = ImageFont.truetype(FONT_BOLD_PATH, base_sz)
    max_sub_w = W - (260 if is_wide else 130)
    for ln in lines:
        if (font.getbbox(ln)[2] - font.getbbox(ln)[0]) > max_sub_w:
            font = ImageFont.truetype(FONT_BOLD_PATH, base_sz - 5)
            break

    word_index = 0
    line_h = 48 if is_wide else 54
    start_y = (band_h - len(lines) * line_h) // 2

    for li, ln in enumerate(lines):
        words = ln.split()
        space_w = font.getlength(" ")
        word_widths = [font.getlength(w) for w in words]
        total_w = sum(word_widths) + space_w * max(0, len(words) - 1)
        cx = (W - total_w) / 2.0
        cy = start_y + li * line_h
        for w, ww in zip(words, word_widths):
            col = YELLOW if word_index == active_word_index else WHITE
            word_index += 1
            d_sh.text((cx, cy + 4), w, font=font, fill=(0, 0, 0, 235), stroke_width=6, stroke_fill=(0, 0, 0, 220))
            d_txt.text((cx, cy), w, font=font, fill=col, stroke_width=2, stroke_fill=(0, 0, 0, 185))
            cx += ww + space_w

    comb = Image.alpha_composite(sh_layer.filter(ImageFilter.GaussianBlur(radius=6)), txt_layer)
    return rgba_to_bgra(comb)

def make_static_brand_layers(W, source_line, is_wide=False):
    top_band = Image.new("RGBA", (W, 80), (0, 0, 0, 0))
    dt = ImageDraw.Draw(top_band)
    px0 = 80 if is_wide else 72
    pill_box = (px0, 14, px0 + 204, 58)
    dt.rounded_rectangle(pill_box, radius=22, fill=LIME)
    fpill = ImageFont.truetype(FONT_BLACK_PATH, 22)
    b = fpill.getbbox("BİLGİ DOZU")
    pw, ph = b[2] - b[0], b[3] - b[1]
    dt.text((px0 + (204 - pw) // 2, 14 + (44 - ph) // 2 - b[1]), "BİLGİ DOZU", font=fpill, fill=DARK_INK)

    bot_h = 115 if is_wide else 150
    bot_band = Image.new("RGBA", (W, bot_h), (0, 0, 0, 0))
    db = ImageDraw.Draw(bot_band)
    fsmall = ImageFont.truetype(FONT_BOLD_PATH, 17 if is_wide else 19)
    s1 = "*Görseller temsilîdir (AI bilimsel canlandırma)"
    s2 = source_line
    if is_wide:
        # Left: disclaimer & source, Right: BILGI DOZU logo
        db.text((80, 28), s1, font=fsmall, fill=(195, 212, 220, 180))
        db.text((80, 54), s2, font=fsmall, fill=(195, 212, 220, 180))
        flogo = ImageFont.truetype(FONT_BLACK_PATH, 32)
        w_b = flogo.getlength("BİLGİ ")
        w_d = flogo.getlength("DOZU")
        lx = W - 80 - (w_b + w_d)
        db.text((lx, 36), "BİLGİ ", font=flogo, fill=WHITE, stroke_width=2, stroke_fill=(0, 0, 0, 180))
        db.text((lx + w_b, 36), "DOZU", font=flogo, fill=LIME, stroke_width=2, stroke_fill=(0, 0, 0, 180))
    else:
        for idx_s, st in enumerate([s1, s2]):
            sw = fsmall.getlength(st)
            db.text(((W - sw) / 2, 8 + idx_s * 25), st, font=fsmall, fill=(195, 212, 220, 175))
        flogo = ImageFont.truetype(FONT_BLACK_PATH, 34)
        w_b = flogo.getlength("BİLGİ ")
        w_d = flogo.getlength("DOZU")
        lx = (W - (w_b + w_d)) / 2
        db.text((lx, 74), "BİLGİ ", font=flogo, fill=WHITE, stroke_width=2, stroke_fill=(0, 0, 0, 180))
        db.text((lx + w_b, 74), "DOZU", font=flogo, fill=LIME, stroke_width=2, stroke_fill=(0, 0, 0, 180))

    return rgba_to_bgra(top_band), rgba_to_bgra(bot_band)

def make_cta_follow_button_frames(W, is_wide=False, n_pulse_steps=16):
    """Pre-renders 16 pulse frames of sleek animated '🔔 TAKİP ET +' pill button for instant 60fps blending."""
    band_h = 115 if is_wide else 130
    base_w, base_h = (360, 74) if is_wide else (410, 84)
    bell = render_emoji_icon("🔔", target_px=(34 if is_wide else 38))
    fbtn = ImageFont.truetype(FONT_BLACK_PATH, 29 if is_wide else 33)
    label = "TAKİP ET  +"
    lb = fbtn.getbbox(label)
    lw, lh = lb[2] - lb[0], lb[3] - lb[1]

    frames = []
    for step in range(n_pulse_steps):
        phase = (step / float(n_pulse_steps)) * 2.0 * np.pi
        scale = 1.0 + 0.045 * np.sin(phase)
        glow_a = int(130 + 85 * (0.5 + 0.5 * np.sin(phase)))

        pw = int(base_w * scale)
        ph = int(base_h * scale)
        x0 = (W - pw) // 2
        y0 = (band_h - ph) // 2

        glow_layer = Image.new("RGBA", (W, band_h), (0, 0, 0, 0))
        dg = ImageDraw.Draw(glow_layer)
        dg.rounded_rectangle((x0 - 6, y0 - 6, x0 + pw + 6, y0 + ph + 6), radius=ph // 2 + 6, fill=(255, 34, 68, glow_a))
        glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=10))

        fg_layer = Image.new("RGBA", (W, band_h), (0, 0, 0, 0))
        df = ImageDraw.Draw(fg_layer)
        df.rounded_rectangle((x0, y0, x0 + pw, y0 + ph), radius=ph // 2, fill=CTA_RED, outline=LIME, width=3)

        content_w = bell.width + 14 + lw
        cx = (W - content_w) // 2
        by = (band_h - bell.height) // 2
        fg_layer.paste(bell, (cx, by), bell)
        tx = cx + bell.width + 14
        ty = (band_h - lh) // 2 - lb[1]
        df.text((tx, ty), label, font=fbtn, fill=WHITE, stroke_width=1, stroke_fill=(0, 0, 0, 140))

        comb = Image.alpha_composite(glow_layer, fg_layer)
        frames.append(rgba_to_bgra(comb))
    return frames

def pack_fast_band(bgra_band):
    """Crops BGRA band to tight non-zero alpha bbox and precomputes uint16 alpha/fg for 8x faster blending."""
    ys, xs = np.where(bgra_band[:, :, 3] > 2)
    if len(ys) == 0:
        return None
    ry0, ry1 = int(ys.min()), int(ys.max()) + 1
    rx0, rx1 = int(xs.min()), int(xs.max()) + 1
    sub = bgra_band[ry0:ry1, rx0:rx1]
    a16 = ((sub[:, :, 3:4].astype(np.uint16) * 257) >> 8)  # 0..256
    fg16 = sub[:, :, :3].astype(np.uint16)
    pre_fg = fg16 * a16  # pre-multiplied for opacity=1.0
    inv_a = 256 - a16
    return (ry0, ry1, rx0, rx1, fg16, a16, pre_fg, inv_a)

def blend_fast_band(frame_bgr, y_base, packed, opacity=1.0):
    if packed is None or opacity <= 0.01:
        return
    ry0, ry1, rx0, rx1, fg16, a16, pre_fg, inv_a = packed
    roi = frame_bgr[y_base + ry0 : y_base + ry1, rx0 : rx1]
    if opacity >= 0.995:
        frame_bgr[y_base + ry0 : y_base + ry1, rx0 : rx1] = ((roi.astype(np.uint16) * inv_a + pre_fg) >> 8).astype(np.uint8)
    else:
        op_i = int(opacity * 256.0)
        eff_a = (a16 * op_i) >> 8
        frame_bgr[y_base + ry0 : y_base + ry1, rx0 : rx1] = ((roi.astype(np.uint16) * (256 - eff_a) + fg16 * eff_a) >> 8).astype(np.uint8)

def mix_master_audio_lufs(scenes_meta, total_dur, out_wav):
    """Measure stems, set the music baseline, and duck it during narration."""
    if __package__:
        from .audio_balance import mix_speech_and_music
    else:
        from audio_balance import mix_speech_and_music
    return mix_speech_and_music(scenes_meta, BGM_PATH, total_dur, out_wav)

def render_video_master(
    out_mp4, scenes_cfg, vo_files, plates_bgr, source_line,
    is_wide=False, target_min_dur=None, target_max_dur=None,
    *, fixed_scenes_meta=None, master_audio_source=None,
):
    t_t0 = time.time()
    W, H = (1920, 1080) if is_wide else (1080, 1920)
    UPS_W, UPS_H = (2400, 1350) if is_wide else (1350, 2400)
    FPS = globals().get("FPS_HEDEF", 30)   # kural: 60 fps (uret.py ayarlar.json'dan set eder)
    CROSS_DISSOLVE = 0.50
    N = len(scenes_cfg)
    if not N or len(vo_files) != N or len(plates_bgr) != N:
        raise ValueError("Her sahne için tek ses kaydı ve tek görsel gereklidir")
    if master_audio_source and not fixed_scenes_meta:
        raise ValueError("Onaylı sesi korumak için doğrulanmış sahne zamanları da gereklidir")
    if master_audio_source and os.path.abspath(master_audio_source) == os.path.abspath(out_mp4):
        raise ValueError("Yeni çıktı onaylı eski dosyanın üzerine yazılamaz")

    vo_durs = [wav_duration(vf) for vf in vo_files]
    sum_vo = sum(vo_durs)

    # Calibrate GAP cleanly so Shorts always hit 51.8s..56.5s (strictly inside 50..58s!)
    LEAD_IN = 0.25
    TAIL_OUT = 1.05
    if target_min_dur is not None:
        jitter = ((hash(out_mp4) % 32) / 10.0); desired = max(target_min_dur + 1.2 + jitter, min(target_max_dur - 0.8, sum_vo + (0.48 + jitter*0.12) * (N - 1) + LEAD_IN + TAIL_OUT))
        GAP = max(0.28, (desired - sum_vo - LEAD_IN - TAIL_OUT) / float(N - 1))
    else:
        GAP = 0.55

    scenes_meta = []
    cursor = 0.0
    for idx, vd in enumerate(vo_durs):
        s_start = cursor
        vo_start = s_start + (LEAD_IN if idx == 0 else GAP / 2.0)
        vo_end = vo_start + vd
        s_end = (vo_end + GAP / 2.0) if idx < (N - 1) else (vo_end + TAIL_OUT)
        scenes_meta.append({
            "index": idx + 1, "scene_start": s_start, "scene_end": s_end,
            "vo_start": vo_start, "vo_end": vo_end, "vo_dur": vd, "vo_file": vo_files[idx]
        })
        cursor = s_end

    if fixed_scenes_meta is not None:
        if len(fixed_scenes_meta) != N:
            raise ValueError("Onaylı sesin sahne zamanları eksik")
        restored = []
        for idx, (saved, vd) in enumerate(zip(fixed_scenes_meta, vo_durs)):
            sm = dict(saved)
            if abs(float(sm["vo_dur"]) - vd) > 0.01:
                raise ValueError("Onaylı sesin sahne kaydı farklı")
            if not (float(sm["scene_start"]) <= float(sm["vo_start"]) < float(sm["vo_end"]) <= float(sm["scene_end"])):
                raise ValueError("Kaydedilmiş sahne zamanları geçersiz")
            if abs((float(sm["vo_end"]) - float(sm["vo_start"])) - vd) > 0.01:
                raise ValueError("Onaylı ses süresi ile sahne süresi uyuşmuyor")
            if idx and abs(float(sm["scene_start"]) - float(restored[-1]["scene_end"])) > 0.02:
                raise ValueError("Kaydedilmiş sahneler arası zaman boşluğu")
            sm["vo_file"] = vo_files[idx]
            restored.append(sm)
        scenes_meta = restored

    TOTAL_DUR = scenes_meta[-1]["scene_end"]
    TOTAL_FRAMES = int(round(TOTAL_DUR * FPS))

    # Motion presets cycling cleanly across scenes
    motion_presets = [
        ((1.00, 1.14), (0.0, 0.0),   (22.0, -22.0)),
        ((1.00, 1.13), (-22.0, 22.0),(12.0, -12.0)),
        ((1.01, 1.15), (0.0, 0.0),   (18.0, -18.0)),
        ((1.00, 1.13), (18.0, -18.0),(20.0, -20.0)),
        ((1.00, 1.12), (-16.0, 16.0),(-18.0, 18.0)),
        ((1.01, 1.13), (14.0, -14.0),(18.0, -18.0)),
        ((1.00, 1.14), (-20.0, 20.0),(14.0, -14.0)),
        ((1.01, 1.13), (16.0, -16.0),(-16.0, 16.0)),
        ((1.01, 1.12), (0.0, 0.0),   (16.0, -16.0)),
    ]

    # Top & bottom legibility scrim
    top_h = 250 if is_wide else 460
    bot_h = 260 if is_wide else 360
    scrim_top_u16 = np.round((0.48 + 0.52 * (np.linspace(0, 1, top_h, dtype=np.float32)[:, None, None] ** 1.4)) * 256.0).astype(np.uint16)
    scrim_bot_u16 = np.round((0.44 + 0.56 * (np.linspace(1, 0, bot_h, dtype=np.float32)[:, None, None] ** 1.3)) * 256.0).astype(np.uint16)

    tb_raw, bb_raw = make_static_brand_layers(W, source_line, is_wide=is_wide)
    top_brand_pk = pack_fast_band(tb_raw)
    bot_brand_pk = pack_fast_band(bb_raw)
    cta_btn_pks  = [pack_fast_band(x) for x in make_cta_follow_button_frames(W, is_wide=is_wide, n_pulse_steps=20)]

    if __package__:
        from .karaoke_timing import KaraokeAligner, subtitle_groups, validate_alignment, active_word_at
    else:
        from karaoke_timing import KaraokeAligner, subtitle_groups, validate_alignment, active_word_at

    # Every subtitle timeline must be measured from its actual narration file.
    # Automatic forced alignment is only used if precomputed word times are
    # absent; missing dependencies or mismatched audio fail closed.
    aligner = None
    karaoke_per_scene = []
    for sm, sc in zip(scenes_meta, scenes_cfg):
        alignment = sc.get("karaoke")
        if alignment is None:
            if aligner is None:
                aligner = KaraokeAligner(model_name=os.environ.get("BD_KARAOKE_MODEL", "small"))
            alignment = aligner.align(sm["vo_file"], sc["subs"], verify_asr=True)
        validate_alignment(sc["subs"], alignment, sm["vo_dur"], sm["vo_file"])
        karaoke_per_scene.append(alignment)
    if aligner is not None:
        del aligner
        import gc
        gc.collect()

    upper_titles_pk = []
    sub_timeline = []
    for sm, sc, alignment in zip(scenes_meta, scenes_cfg, karaoke_per_scene):
        _t1 = sc.get("t1") or sc.get("title_line1", "")
        _t2 = sc.get("t2") or sc.get("title_line2", "")
        upper_titles_pk.append(pack_fast_band(make_upper_title_band(W, sc["emoji"], _t1, _t2, is_wide=is_wide)))
        for group in subtitle_groups(sc["subs"], alignment, sm["vo_start"], sm["vo_dur"]):
            text = group["text"]
            group["white_pk"] = pack_fast_band(make_subtitle_band(W, text, is_wide=is_wide))
            group["word_pks"] = [
                pack_fast_band(make_subtitle_band(W, text, is_wide=is_wide, active_word_index=w["index"]))
                for w in group["words"]
            ]
            sub_timeline.append(group)

    master_wav = None
    if master_audio_source:
        audio_input = str(master_audio_source)
    else:
        master_wav = f"/var/tmp/master_mix_{os.path.basename(out_mp4)}.wav"
        mix_master_audio_lufs(scenes_meta, TOTAL_DUR, master_wav)
        audio_input = master_wav

    def render_kb(s_idx, prog):
        p = max(0.0, min(1.0, prog))
        ease = 0.70 * p + 0.30 * (0.5 - 0.5 * np.cos(np.pi * p))
        (z0, z1), (px0, px1), (py0, py1) = motion_presets[s_idx % len(motion_presets)]
        zoom = z0 + (z1 - z0) * ease
        dx = px0 + (px1 - px0) * ease
        dy = py0 + (py1 - py0) * ease
        win_w = (UPS_W * 0.918) / zoom
        win_h = (UPS_H * 0.918) / zoom
        x0 = (UPS_W / 2.0) + dx - win_w / 2.0
        y0 = (UPS_H / 2.0) + dy - win_h / 2.0
        M = np.array([[win_w / float(W), 0.0, x0], [0.0, win_h / float(H), y0]], dtype=np.float32)
        return cv2.warpAffine(plates_bgr[s_idx], M, (W, H), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_REFLECT_101)

    os.makedirs(os.path.dirname(out_mp4), exist_ok=True)
    log_path = f"/tmp/ff_{os.path.basename(out_mp4)}.log"
    if __package__:
        from .audio_balance import ffmpeg_executable
    else:
        from audio_balance import ffmpeg_executable
    ffmpeg_cmd = [
        ffmpeg_executable(), "-y",
        "-f", "rawvideo", "-vcodec", "rawvideo", "-pix_fmt", "bgr24",
        "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
        "-i", audio_input,
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264", "-preset", os.environ.get("BD_X264_PRESET", "medium"),
        "-crf", os.environ.get("BD_X264_CRF", "19"),
        "-profile:v", "high", "-pix_fmt", "yuv420p",
        "-c:a", "copy" if master_audio_source else "aac",
        *( [] if master_audio_source else ["-b:a", "192k"] ),
        "-movflags", "+faststart", out_mp4
    ]
    log_f = open(log_path, "w")
    proc = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE, stderr=log_f)

    half_cd = CROSS_DISSOLVE / 2.0
    bar_y0, bar_y1 = (28, 34) if is_wide else (58, 64)
    bar_x0, bar_x1 = (80, W - 80) if is_wide else (72, W - 72)
    top_pill_y = 42 if is_wide else 74
    title_y    = 44 if is_wide else 155
    sub_y      = 770 if is_wide else 1240
    cta_y      = 650 if is_wide else 1535
    bot_y      = (H - 120) if is_wide else 1740

    last_sm = scenes_meta[-1]

    for f_idx in range(TOTAL_FRAMES):
        t = f_idx / float(FPS)
        active_idx = N - 1
        for idx, sm in enumerate(scenes_meta):
            if t < sm["scene_end"] or idx == (N - 1):
                active_idx = idx
                break

        sm_cur = scenes_meta[active_idx]
        vis_s = sm_cur["scene_start"] - (half_cd if active_idx > 0 else 0.0)
        vis_e = sm_cur["scene_end"] + (half_cd if active_idx < (N - 1) else 0.0)
        frame = render_kb(active_idx, (t - vis_s) / max(0.1, vis_e - vis_s))

        if active_idx < (N - 1) and t >= (sm_cur["scene_end"] - half_cd):
            alpha_cd = (t - (sm_cur["scene_end"] - half_cd)) / CROSS_DISSOLVE
            sm_nxt = scenes_meta[active_idx + 1]
            ns = sm_nxt["scene_start"] - half_cd
            ne = sm_nxt["scene_end"] + (half_cd if (active_idx + 1) < (N - 1) else 0.0)
            frame_nxt = render_kb(active_idx + 1, (t - ns) / max(0.1, ne - ns))
            frame = cv2.addWeighted(frame, 1.0 - alpha_cd, frame_nxt, alpha_cd, 0.0)
        elif active_idx > 0 and t < (sm_cur["scene_start"] + half_cd):
            alpha_cd = (t - (sm_cur["scene_start"] - half_cd)) / CROSS_DISSOLVE
            sm_prv = scenes_meta[active_idx - 1]
            ps = sm_prv["scene_start"] - (half_cd if (active_idx - 1) > 0 else 0.0)
            pe = sm_prv["scene_end"] + half_cd
            frame_prv = render_kb(active_idx - 1, (t - ps) / max(0.1, pe - ps))
            frame = cv2.addWeighted(frame_prv, 1.0 - alpha_cd, frame, alpha_cd, 0.0)

        frame[:top_h] = ((frame[:top_h].astype(np.uint16) * scrim_top_u16) >> 8).astype(np.uint8)
        frame[H - bot_h :] = ((frame[H - bot_h :].astype(np.uint16) * scrim_bot_u16) >> 8).astype(np.uint8)

        # Signature @bilgidozuofficial Progress Bar
        frame[bar_y0:bar_y1, bar_x0:bar_x1] = ((frame[bar_y0:bar_y1, bar_x0:bar_x1].astype(np.uint16) * 115 + 11264) >> 8).astype(np.uint8)
        fill_x = bar_x0 + int((bar_x1 - bar_x0) * (f_idx / max(1, TOTAL_FRAMES - 1)))
        if fill_x > bar_x0:
            frame[bar_y0:bar_y1, bar_x0:fill_x] = (46, 255, 220)

        blend_fast_band(frame, top_pill_y, top_brand_pk, 1.0)
        blend_fast_band(frame, bot_y, bot_brand_pk, 1.0)

        dt_in = t - sm_cur["scene_start"]
        dt_out = sm_cur["scene_end"] - t
        title_op = min(1.0, max(0.0, dt_in / 0.25), max(0.0, dt_out / 0.25))
        blend_fast_band(frame, title_y, upper_titles_pk[active_idx], title_op)

        for group in sub_timeline:
            if group["start"] <= t < group["end"]:
                index = active_word_at(group, t)
                band = group["white_pk"] if index is None else group["word_pks"][index]
                # Fade at video boundaries only, not at every 100-400 ms word.
                blend_fast_band(frame, sub_y, band, 1.0)
                break

        if t >= last_sm["scene_start"] + 0.15:
            cta_dt = t - (last_sm["scene_start"] + 0.15)
            cta_rem = TOTAL_DUR - t
            cta_op = min(1.0, cta_dt / 0.28, max(0.0, cta_rem / 0.45))
            pulse_idx = int((cta_dt * 24.0)) % len(cta_btn_pks)
            blend_fast_band(frame, cta_y, cta_btn_pks[pulse_idx], cta_op)

        if t < 0.35:
            frame = (frame.astype(np.float32) * (t / 0.35)).astype(np.uint8)
        elif t > (TOTAL_DUR - 0.45):
            frame = (frame.astype(np.float32) * max(0.0, (TOTAL_DUR - t) / 0.45)).astype(np.uint8)

        proc.stdin.write(frame.tobytes())

    proc.stdin.close()
    ret = proc.wait()
    log_f.close()
    if master_wav and os.path.exists(master_wav):
        os.remove(master_wav)
    if ret != 0:
        raise RuntimeError(open(log_path).read()[-1200:])
    mb = os.path.getsize(out_mp4) / (1024 * 1024)
    print(f"✅ Rendered {os.path.basename(out_mp4)}: dur={TOTAL_DUR:.2f}s | {mb:.2f} MB | {time.time()-t_t0:.1f}s", flush=True)
    return TOTAL_DUR, scenes_meta

if __name__ == "__main__":
    spec = json.load(open("/home/user/pilot_engine/prod/master_spec.json", encoding="utf-8"))
    shorts_map = {s["num"]: s for s in spec["shorts"]}
    uzun_map   = {u["num"]: u for u in spec["uzunlar"]}

    targets = sys.argv[1:]
    for tgt in targets:
        if tgt.startswith("s"):
            n = int(tgt[1:])
            s = shorts_map[n]
            plates = build_6_vertical_plates(f"/home/user/pilot_engine/prod/ai/hero_{n}.png", seed_base=n)
            vos = [f"/home/user/pilot_engine/prod/scenes_vo/v{n}/scene_{i:02d}.wav" for i in range(1, 7)]
            out_mp4 = f"/var/tmp/renders/video_{n}.mp4"
            dur, meta = render_video_master(
                out_mp4, s["scenes"], vos, plates, s["source_line"],
                is_wide=False, target_min_dur=50.5, target_max_dur=57.5
            )
            assert 50.0 <= dur <= 58.0, f"Short duration {dur} out of 50..58s"
            json.dump({"dur": dur, "scenes": meta}, open(f"/home/user/pilot_engine/prod/meta_s{n}.json", "w"))
        elif tgt.startswith("u"):
            un = int(tgt[1:])
            u = uzun_map[un]
            ps = shorts_map[u["parent_short"]]
            # Combine first 5 core scenes of parent Short + 4 deep-dive extra chapters = 9 chapters!
            scenes_9 = ps["scenes"][:5] + u["extra_scenes"]
            vos_9 = (
                [f"/home/user/pilot_engine/prod/scenes_vo/v{u['parent_short']}/scene_{i:02d}.wav" for i in range(1, 6)] +
                [f"/home/user/pilot_engine/prod/scenes_vo/u{un}/extra_{i:02d}.wav" for i in range(1, len(u["extra_scenes"]) + 1)]
            )
            extra_wide = "/home/user/pilot_engine/prod/ai/hero_u14_wide.png" if un == 14 else None
            plates_9 = build_9_horizontal_plates(f"/home/user/pilot_engine/prod/ai/hero_{u['parent_short']}.png", extra_wide, seed_base=un)[:len(scenes_9)]
            out_mp4 = f"/var/tmp/renders/uzun_video_{un}.mp4"
            dur, meta = render_video_master(
                out_mp4, scenes_9, vos_9, plates_9, u["source_line"],
                is_wide=True, target_min_dur=None, target_max_dur=None
            )
            json.dump({"dur": dur, "scenes": meta}, open(f"/home/user/pilot_engine/prod/meta_u{un}.json", "w"))
